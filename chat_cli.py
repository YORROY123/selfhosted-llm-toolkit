# -*- coding: utf-8 -*-
"""
llm 聊天小工具 —— 只用 Python 內建功能，不需要 pip install 任何東西。

用法:
  1. 把你的 key 填進下面 API_KEY（或放在同資料夾的 api_key.txt 裡）
  2. 確認 BASE_URL 選對（內網 / 公網，看發 key 時說的是哪條）
  3. 雙擊 llm_chat.bat，或在終端機執行: python llm_chat.py
  4. 想換模型: python llm_chat.py my-strong
     離開: 打 exit 或按 Ctrl+C
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

# ── 你要改的只有這兩行 ───────────────────────────────────────────
API_KEY = ""                                        # 填 sk-... （或用 api_key.txt）
BASE_URL = "https://YOUR-ENDPOINT.example.com/v1"  # 公網 key 用這條（任何網路都行，已測過通）
# BASE_URL = "http://192.0.2.10:4000/v1"          # 內網 key 用這條（這台電腦要先開 Tailscale）
# ─────────────────────────────────────────────────────────────────

HERE = os.path.dirname(os.path.abspath(__file__))


def load_key():
    if API_KEY.strip():
        return API_KEY.strip()
    keyfile = os.path.join(HERE, "api_key.txt")
    if os.path.exists(keyfile):
        with open(keyfile, encoding="utf-8") as f:
            saved = f.read().strip()
        if saved:
            return saved
    if os.environ.get("LLM_API_KEY"):
        return os.environ["LLM_API_KEY"].strip()
    print("還沒設定 key。在這個視窗裡按滑鼠右鍵就可以貼上。")
    key = input("貼上你的 API key (sk-...) 然後按 Enter： ").strip()
    if key:
        try:
            with open(keyfile, "w", encoding="utf-8") as f:
                f.write(key + "\n")
            print("（已經記住了，存在 api_key.txt，下次不會再問）\n")
        except OSError as e:
            print("（存檔失敗，下次還要再貼一次：%s）\n" % e)
    return key


def post(path, key, body=None, method="POST"):
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method=method,
    )
    return urllib.request.urlopen(req, timeout=300, context=ssl.create_default_context())


def explain(err):
    """把 HTTP 錯誤碼翻成人話。"""
    codes = {
        401: "key 錯了或沒帶，也可能是你用錯網址（內網 key 打公網網址就會這樣）",
        403: "這把 key 不能用這個模型",
        429: "送太快或太多條，等幾秒再試",
    }
    if isinstance(err, urllib.error.HTTPError):
        return "HTTP %s：%s" % (err.code, codes.get(err.code, "後端忙或重啟中，等一兩分鐘再試"))
    return "連不上：%s（內網網址要先開 Tailscale）" % err


def list_models(key):
    try:
        with post("/models", key, method="GET") as r:
            return [m["id"] for m in json.load(r).get("data", [])]
    except Exception as e:
        print("[錯誤] 取模型清單失敗：" + explain(e))
        sys.exit(1)


def chat(key, model, messages):
    """送一輪對話，邊收邊印，回傳完整回答。"""
    body = {"model": model, "messages": messages, "stream": True}
    if model == "my-fast":   # flash 的定位是快問快答，不讓它花時間思考
        body["chat_template_kwargs"] = {"enable_thinking": False}
    try:
        resp = post("/chat/completions", key, body)
    except Exception as e:
        print("[錯誤] " + explain(e))
        return None

    parts = []
    thinking = False
    dots = 0
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"]
            except (ValueError, KeyError, IndexError):
                continue
            if delta.get("reasoning_content"):   # 模型在想，印點點免得看起來像當掉
                if not thinking:
                    thinking = True
                    print("（思考中", end="", flush=True)
                if dots < 40:
                    print("．", end="", flush=True)
                    dots += 1
                continue
            piece = delta.get("content") or ""
            if piece:
                if thinking:
                    print("）")
                    thinking = False
                if not parts:
                    piece = piece.lstrip()      # 答案開頭多餘的空行拿掉
                    if not piece:
                        continue
                parts.append(piece)
                print(piece, end="", flush=True)
    if thinking:
        print("）")
    print()
    return "".join(parts)


def main():
    key = load_key()
    model = sys.argv[1] if len(sys.argv) > 1 else "my-fast"

    available = list_models(key)
    print("連上了。這把 key 可以用的模型：" + ", ".join(available))
    if model not in available:
        print("（%s 不在清單裡，改用 %s）" % (model, available[0]))
        model = available[0]
    print("現在用 %s ——  打字就送出，打 exit 離開。\n" % model)

    # 預設講繁體中文（模型本來會回簡體）。不想要就把下面這行刪掉。
    messages = [{"role": "system", "content": "請用繁體中文回答。"}]
    while True:
        try:
            user = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user.lower() in ("exit", "quit", "bye"):
            break
        messages.append({"role": "user", "content": user})
        print("llm > ", end="", flush=True)
        reply = chat(key, model, messages)
        if reply is None:          # 這輪失敗，別把壞的對話留在歷史裡
            messages.pop()
            continue
        messages.append({"role": "assistant", "content": reply})
        print()


if __name__ == "__main__":
    main()
