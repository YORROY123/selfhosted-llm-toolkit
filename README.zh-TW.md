# 把自架的 OpenAI 相容 LLM 接到你習慣的工具上

*[English](README.md)*

一個「OpenAI 相容」的端點（vLLM / SGLang / Ollama / LM Studio，前面常常掛一層
LiteLLM），要怎麼接到日常真的會用的工具上。四條路，各自踩到的坑都寫在下面。

所有 Python 腳本**只用內建函式庫**，不需要 `pip install` 任何東西。

---

## 你需要先有的東西

| | |
|---|---|
| 一個 OpenAI 相容端點 | 像 `https://your-host/v1`，支援 `/models` 和 `/chat/completions` |
| 一把 API key | 放進 `api_key.txt`（已在 `.gitignore` 裡） |
| Python 3 | 只有終端機聊天和代理需要 |

先確認端點活著。回 `401` 代表「伺服器在、只是還沒帶 key」，那是好消息：

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://YOUR-ENDPOINT.example.com/v1/models
```

回 `000` 是連不到（VPN / Tailscale 沒開，或網路不通）。

---

## 四條路

### 1. 終端機聊天 —— `chat_cli.py`

最小可用的東西。改 `BASE_URL`，雙擊 `chat_cli.bat`，第一次會問你 key 並自己記起來。

```
連上了。這把 key 可以用的模型：my-strong, my-fast
現在用 my-fast ——  打字就送出，打 exit 離開。

你 > 用一句話介紹台北
llm > 台北是……
```

會把模型的思考過程顯示成「（思考中．．．）」的進度，不然看起來像當掉。

### 2. 網頁介面 —— `chat.html`

單一檔案，雙擊用瀏覽器打開就好，**不用架伺服器**（端點的 CORS 要是 `*`；LiteLLM 預設就是）。

- 可以管理**多個供應商**，模型清單按供應商分組
- 串流、思考過程收在可展開區塊、停止鍵、複製鍵
- 對話存在瀏覽器裡，關掉再開還在
- 深色模式、手機寬度可用
- key 只存在本機瀏覽器的 localStorage

每個供應商有個「用 vLLM 參數關思考」的選項：勾了會送
`chat_template_kwargs: {enable_thinking: false}`。接 OpenAI 官方這類服務要取消勾選，
否則它會因為多了不認識的參數而拒絕請求。

### 3. Pi coding agent

[Pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) 原生支援多供應商，
不需要代理。把 `examples/pi-models.json` 放到 `~/.pi/agent/models.json`，
`examples/pi-settings.json` 放到 `~/.pi/agent/settings.json`，改掉裡面的網址和 key。

```bash
pi                      # 互動介面
pi --print "問題"        # 問一句就結束
git diff | pi --print "審這段修改"
```

`/model` 挑模型、`/thinking` 挑思考等級，在清單上按 `Ctrl+S` 存成預設。
`/login` 可以再登入 Anthropic、OpenAI、Gemini 等 25 家以上的供應商，
它們會併進同一個 `/model` 清單。

### 4. Claude Code —— `claude_router.py`

Claude Code 只認一個 `ANTHROPIC_BASE_URL`，沒有多供應商概念。
這支代理按**模型名字**分流：

```
model 開頭是 my-  →  轉給你的端點，認證換成你的 key
其他（claude-*）  →  原封不動轉給 api.anthropic.com，用你自己的登入
```

兩步：

1. 把 `examples/claude-settings-modelPicker.json` 的 `modelPicker` 區塊
   合併進 `~/.claude/settings.json`
2. 雙擊 `claude_pick.bat`

進去打 `/model`，清單裡會同時有真 Claude 和你自己的模型，**同一個 session 隨時切換**。

> **你的 Anthropic 登入憑證會經過這支本機代理。** 它只在 `127.0.0.1` 上聽，
> 而且程式碼裡沒有任何一行會把認證寫進檔案或印出來 —— 可以自己搜 `authorization` 確認。

---

## 踩過的坑

這些都是實測撞到的，而且大多查不到現成的說明。

### Claude Code 會在 `messages` 裡夾 `system` 訊息

症狀是整個請求被打回：

```
litellm.BadRequestError: OpenAIException - System message must be at the beginning.
```

Claude Code 的 system-reminder 是用 `{"role": "system", ...}` 夾在 `messages` 陣列裡送的，
而且**擺在 user 訊息後面**。後端（vLLM）要求 system 必須在最前面。

`claude_router.py` 的做法是把那些訊息原地改成 `role: "user"`，保留它在對話中的位置。

### 思考模型配上太小的 `max_tokens` 會回空的 `content`

`max_tokens` 設 200~800 時，思考還沒結束預算就燒完了，回應是
`stop_reason: "max_tokens"` 加上 `content: []`，看起來像模型壞掉。
放大到 8192 就一切正常。

**不要用小 `max_tokens` 去「快速測試」一個會思考的模型。** 會得到完全錯誤的結論。

反過來，Claude Code 預設送 `max_tokens: 32000`，對 64K 上下文的模型來說留給輸入的空間不夠，
代理會把它夾到 16384。

### 速率限制看起來像當機

key 的並行上限很低時（例如並行 1、每分鐘 10 次），agent 一輪會發好幾個請求，很容易撞到。
**撞到時它不會報錯，只是在那邊等。** 看起來跟「模型思考停不下來」一模一樣。

本專案的代理碰到 429 會自動重試退避。但如果你發現「開頭很久不出字」，
先去看 key 的上限，不要先怪模型。

### Pi：`models.json` 最外層一定要有 `providers`

少了那層 Pi 不會認，而且不太會告訴你為什麼。

### Pi：`reasoning` 設 `false` 的話只會有 `off` 一個思考等級

```
Unknown thinking level "medium". Available levels: off.
```

要 `/thinking` 給你完整選項就得設 `"reasoning": true`。

### Pi 不會過濾你沒定義的思考等級

文件說它會「clamp 到模型支援的範圍」，實際上**不會**。
`samplingParamsByThinkingLevel` 裡沒定義的等級，Pi 照樣接受，然後送一個
後端不認得的值出去，於是撞 400。

Pi 有七個等級：`off` / `minimal` / `low` / `medium` / `high` / `xhigh` / `max`，
**全部都要列**。

### 後端支援的 `reasoning_effort` 值不一定是你以為的那幾個

這個 vLLM 部署只認 `low` / `medium` / `xhigh`，**沒有 `high`**：

```
Unexpected reasoning effort high. Supported types are xhigh (default), medium, and low.
```

所以 Pi 的 `high` 等級要對應到 `"xhigh"`。先用 curl 試一次，不要照抄 OpenAI 的值。

### 改完 `models.json` 要 `/reload`

執行中的 Pi session 載的是舊設定。打 `/reload`（或 `/model`，它也會重讀）。

### LiteLLM 有 Anthropic 格式的 `/v1/messages`

如果你的端點前面是 LiteLLM，`/v1/messages` 通常是通的，`x-api-key` 和
`Authorization: Bearer` 兩種認證都收。tool calling 也正常運作。
這是 Claude Code 那條路能成立的前提。

### Claude Code 會把真實憑證送到自訂的 base URL

設了 `ANTHROPIC_BASE_URL` 而**不設** `ANTHROPIC_AUTH_TOKEN` 時，Claude Code 會把
自己的 OAuth token 送到那個網址。分流代理因此可以原封不動轉給 Anthropic。
反過來說，這也意味著**你指到的任何網址都會拿到你的憑證** —— 只指向你信任的東西。

### 模型自我介紹的名字不代表你接到了什麼

問它「你是哪個模型」，它可能回一個完全無關的名字。要確認實際用的是什麼，
在 Pi 裡看 `PI_PROVIDER` / `PI_MODEL` 環境變數，或看請求的 usage / cost 欄位。

---

## 檔案

| 檔案 | 用途 |
|---|---|
| `chat_cli.py` / `chat_cli.bat` | 終端機聊天 |
| `chat.html` | 單檔網頁介面，多供應商 |
| `claude_router.py` / `claude_pick.bat` | Claude Code 分流代理 |
| `examples/pi-models.json` | Pi 的供應商與模型設定 |
| `examples/pi-settings.json` | Pi 的預設值 |
| `examples/claude-settings-modelPicker.json` | Claude Code 的 `/model` 清單 |

## 授權

MIT
