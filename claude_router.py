# -*- coding: utf-8 -*-
"""
llm 分流代理 —— 讓 Claude Code 在同一個 session 裡可以用 /model 切換
「真 Claude」和「自己機器上的 llm」。只用 Python 內建功能。

怎麼分流：看請求裡的 model 名字。
  model 開頭是 llm  →  轉給你的 llm，認證換成 llm key
  其他（claude-*）  →  原封不動轉給 api.anthropic.com，用你自己的登入憑證

轉給 llm 時會順手修兩件事（不然 llm 收不下 Claude Code 的請求）：
  1. Claude Code 會在 messages 裡夾 role=system 的訊息（system-reminder），
     而且擺在 user 之後。後端 vLLM 要求 system 在最前面，否則 400：
     "System message must be at the beginning."
  2. 它預設 max_tokens=32000，對 64K 上下文的模型留給輸入的空間不夠。

安全性：你的 Anthropic 登入憑證會經過這支程式（它只在 127.0.0.1 上聽，
不對外）。程式碼裡沒有任何一行會把認證寫進檔案或印出來 —— 可以自己搜 authorization。

用法: 雙擊 claude_pick.bat
"""
import json
import os
import random
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ── 可能要改的 ───────────────────────────────────────────────────
MY_MODEL_PREFIX = "my-"   # 開頭是這個的模型名就轉給自己的端點
LLM_UPSTREAM = "https://YOUR-ENDPOINT.example.com"   # 內網改 http://192.0.2.10:4000
ANTHROPIC_UPSTREAM = "https://api.anthropic.com"
PORT = 8787
LLM_MAX_OUT = 16384      # llm 單次回答上限（64K 上下文，其餘留給輸入）
# ─────────────────────────────────────────────────────────────────

RETRY_ON = (429, 500, 502, 503, 504)
MAX_TRIES = 6
HERE = os.path.dirname(os.path.abspath(__file__))
_lock = threading.Lock()


def load_llm_key():
    f = os.path.join(HERE, "api_key.txt")
    if os.path.exists(f):
        with open(f, encoding="utf-8") as fh:
            k = fh.read().strip()
            if k:
                return k
    if os.environ.get("LLM_API_KEY"):
        return os.environ["LLM_API_KEY"].strip()
    print("找不到 llm key。把它放進同資料夾的 api_key.txt。", file=sys.stderr)
    sys.exit(1)


LLM_KEY = load_llm_key()


def say(msg):
    with _lock:
        print(msg, flush=True)


def is_mine(model):
    return isinstance(model, str) and model.lower().startswith(MY_MODEL_PREFIX)


def fix_for_llm(b):
    """把 Claude Code 的請求改成 llm 收得下的樣子。回傳改了什麼。"""
    notes = []
    msgs = b.get("messages")
    if isinstance(msgs, list):
        moved = 0
        for i, m in enumerate(msgs):
            if isinstance(m, dict) and m.get("role") == "system":
                msgs[i] = dict(m, role="user")   # 原地改，保留它在對話裡的位置
                moved += 1
        if moved:
            notes.append("%d 個夾在中間的 system 改成 user" % moved)

    mt = b.get("max_tokens")
    if isinstance(mt, int) and mt > LLM_MAX_OUT:
        b["max_tokens"] = LLM_MAX_OUT
        notes.append("max_tokens %d→%d" % (mt, LLM_MAX_OUT))
    return notes


def build_headers(src, to_llm):
    """組上游要的標頭。去 llm 才換認證；去 Anthropic 一律原封不動。"""
    drop = {"host", "content-length", "connection", "accept-encoding"}
    if to_llm:
        drop |= {"x-api-key", "authorization"}
    out = {}
    for k, v in src.items():
        if k.lower() in drop:
            continue
        out[k] = v
    if to_llm:
        out["x-api-key"] = LLM_KEY
        out["authorization"] = "Bearer " + LLM_KEY
    out["accept-encoding"] = "identity"
    return out


def forward(url, method, headers, raw, retry):
    ctx = ssl.create_default_context()
    for attempt in range(MAX_TRIES if retry else 1):
        req = urllib.request.Request(url, data=raw or None, headers=headers, method=method)
        try:
            return urllib.request.urlopen(req, timeout=900, context=ctx), None
        except urllib.error.HTTPError as e:
            if not retry or e.code not in RETRY_ON or attempt == MAX_TRIES - 1:
                return None, e
            wait = min(2 ** attempt, 8) + random.random()
            say("  (%s，%.1f 秒後重試 %d/%d)" % (e.code, wait, attempt + 2, MAX_TRIES))
            time.sleep(wait)
        except Exception as e:
            return None, e
    return None, None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _err_json(self, status, message):
        data = json.dumps({"type": "error",
                           "error": {"type": "api_error", "message": message}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _relay(self, method):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""

        body = None
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                body = None

        model = body.get("model") if isinstance(body, dict) else None

        # 沒有 model 可判斷時：模型清單給 llm，其餘交給 Anthropic
        if model is None:
            to_llm = self.path.rstrip("/").endswith("/models")
        else:
            to_llm = is_mine(model)

        if to_llm and isinstance(body, dict):
            notes = fix_for_llm(body)
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            say("→ llm  %s%s" % (model, ("：" + "、".join(notes)) if notes else ""))
        elif model is not None:
            say("→ Anthropic  %s" % model)

        upstream = LLM_UPSTREAM if to_llm else ANTHROPIC_UPSTREAM
        hdrs = build_headers(self.headers, to_llm)
        up, err = forward(upstream + self.path, method, hdrs, raw, retry=to_llm)

        if err is not None:
            if isinstance(err, urllib.error.HTTPError):
                data = err.read()
                say("✗ HTTP %s  %s" % (err.code, data[:200].decode("utf-8", "replace")))
                self.send_response(err.code)
                self.send_header("Content-Type",
                                 err.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                say("✗ 連不到 %s：%r" % (upstream, err))
                self._err_json(502, "proxy could not reach upstream: %r" % (err,))
            return
        if up is None:
            self._err_json(502, "proxy failed with no response")
            return

        ctype = up.headers.get("Content-Type", "application/json")
        streaming = "event-stream" in ctype

        self.send_response(up.status)
        self.send_header("Content-Type", ctype)
        if streaming:
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        try:
            if streaming:
                while True:
                    chunk = up.read1(8192) if hasattr(up, "read1") else up.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(("%x\r\n" % len(chunk)).encode())
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            else:
                self.wfile.write(up.read())
        except (BrokenPipeError, ConnectionResetError):
            pass                                  # 客戶端中途離開，正常
        finally:
            up.close()

    def do_POST(self):
        self._relay("POST")

    def do_GET(self):
        self._relay("GET")


if __name__ == "__main__":
    print("llm 分流代理：http://127.0.0.1:%d" % PORT)
    print("  llm-*   → %s" % LLM_UPSTREAM)
    print("  其他    → %s（用你自己的登入）" % ANTHROPIC_UPSTREAM)
    print("這個視窗不要關。\n")
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n代理關掉了。")
