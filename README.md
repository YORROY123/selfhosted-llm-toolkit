# selfhosted-llm-toolkit

*[繁體中文](README.zh-TW.md)*

You have a self-hosted LLM behind an **OpenAI-compatible endpoint** — vLLM, SGLang,
Ollama, LM Studio, usually with LiteLLM in front. This repo connects it to the tools
you actually work in:

| | |
|---|---|
| **Terminal chat** | `chat_cli.py` — stdlib only, nothing to install |
| **Web UI** | `chat.html` — one file, open it in a browser, no server |
| **[Pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) coding agent** | config only, no proxy needed |
| **Claude Code** | `claude_router.py` — switch between real Claude and your own model **in the same session** |

Every Python script uses only the standard library. No `pip install`.

**The most valuable part of this repo is probably [Gotchas](#gotchas)** — failure
modes that are undocumented, misleading, or actively contradict the official docs.
Each one cost real debugging time to find.

> **Note on language:** this README is English, but the CLI and web UI strings are
> Traditional Chinese (they were written for a zh-TW user). They are plain strings
> in `chat_cli.py` and `chat.html` and easy to swap. PRs welcome.

---

## Prerequisites

| | |
|---|---|
| An OpenAI-compatible endpoint | e.g. `https://your-host/v1`, serving `/models` and `/chat/completions` |
| An API key | put it in `api_key.txt` (already in `.gitignore`) |
| Python 3 | only needed for the terminal chat and the router |

Check the endpoint is alive first. A `401` is good news — it means the server is
there and simply wants a key:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://YOUR-ENDPOINT.example.com/v1/models
```

`000` means you cannot reach it at all (VPN/Tailscale down, or wrong host).

---

## 1. Terminal chat — `chat_cli.py`

The smallest useful thing. Set `BASE_URL` at the top, run `chat_cli.bat` (or
`python chat_cli.py`). It asks for your key once and remembers it.

```
Connected. Models available to this key: my-strong, my-fast
Using my-fast — type to send, "exit" to quit.

> Introduce Taipei in one sentence
```

It renders the model's reasoning stream as a progress indicator, so a thinking
model doesn't look like it has frozen.

## 2. Web UI — `chat.html`

A single file. Open it in a browser — **no server required** (your endpoint needs
`Access-Control-Allow-Origin: *`; LiteLLM sets this by default).

- Manage **multiple providers**; the model dropdown groups by provider
- Streaming, collapsible reasoning panel, stop button, copy button
- Conversation persists in `localStorage`
- Dark mode, works at phone width
- Keys never leave the browser

Each provider has a **"disable thinking via vLLM params"** toggle. When on, requests
include `chat_template_kwargs: {enable_thinking: false}`. Turn it **off** for
providers like OpenAI proper, which reject unknown parameters.

## 3. Pi coding agent

Pi supports multiple providers natively — no proxy needed.

1. Copy `examples/pi-models.json` to `~/.pi/agent/models.json`
2. Copy `examples/pi-settings.json` to `~/.pi/agent/settings.json`
3. Edit the URL and key

```bash
pi                           # interactive
pi --print "a question"      # one-shot
git diff | pi --print "review this change"
```

`/model` picks the model, `/thinking` picks the reasoning level, `Ctrl+S` on either
list saves it as the default. `/login` adds Anthropic, OpenAI, Gemini and 20+ other
providers to the same `/model` list.

## 4. Claude Code — `claude_router.py`

Claude Code only understands a single `ANTHROPIC_BASE_URL`; it has no concept of
multiple providers. This proxy routes **by model name**:

```
model starts with "my-"  →  your endpoint, auth swapped to your key
anything else            →  api.anthropic.com, untouched, your own login
```

Two steps:

1. Merge the `modelPicker` block from `examples/claude-settings-modelPicker.json`
   into `~/.claude/settings.json`
2. Run `claude_pick.bat`

Then `/model` lists both real Claude models and your own, switchable mid-session.

> **Your Anthropic credentials pass through this local proxy.** It binds to
> `127.0.0.1` only, and no line in it writes or prints an auth header — grep for
> `authorization` to verify. Review the code before you trust it with your token.

---

## Gotchas

### Claude Code puts a `system` message *inside* `messages`

Symptom — the whole request is rejected:

```
litellm.BadRequestError: OpenAIException - System message must be at the beginning.
```

Claude Code sends its system-reminders as `{"role": "system", ...}` entries inside
the `messages` array, positioned **after** the user message. vLLM requires any
system message to come first.

`claude_router.py` rewrites those entries to `role: "user"` in place, preserving
their position in the conversation.

### A thinking model with a small `max_tokens` returns empty `content`

With `max_tokens` of 200–800, reasoning consumes the whole budget before any answer
is produced. You get `stop_reason: "max_tokens"` and `content: []`, which looks
exactly like a broken model. At 8192 everything works.

**Do not "quick test" a reasoning model with a small `max_tokens`.** You will reach
completely wrong conclusions. (This cost an hour and a wrong diagnosis.)

Conversely, Claude Code defaults to `max_tokens: 32000`, which leaves too little
room for input on a 64K-context model — the router clamps it to 16384.

### Rate limiting looks exactly like a hang

When a key has a low concurrency cap (say 1 parallel, 10 requests/min), an agent
turn fires several requests and hits the limit easily. **It does not raise an
error — it just waits.** This is indistinguishable from "the model is stuck
thinking" unless you check.

The router retries 429 with backoff. But if output is slow to start, check your
key's limits before blaming the model.

### Pi: `models.json` needs a top-level `providers` key

Without that wrapper Pi silently ignores the file.

### Pi: `reasoning: false` leaves you with exactly one thinking level

```
Unknown thinking level "medium". Available levels: off.
```

Set `"reasoning": true` for `/thinking` to offer the full range.

### Pi does **not** clamp thinking levels you haven't defined

The docs say Pi "clamps unsupported thinking levels". In practice it does not.
A level missing from `samplingParamsByThinkingLevel` is still accepted, and Pi
sends a value the backend rejects with a 400.

Pi has seven levels — `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` —
and **all seven must be listed**.

### Valid `reasoning_effort` values are backend-specific

This vLLM deployment accepts `low` / `medium` / `xhigh` and has **no `high`**:

```
Unexpected reasoning effort high. Supported types are xhigh (default), medium, and low.
```

So Pi's `high` level has to map to `"xhigh"`. Probe your backend with curl rather
than assuming OpenAI's value set.

### Edits to `models.json` need `/reload`

A running Pi session holds the old config. `/reload` (or `/model`, which also
re-reads the file).

### LiteLLM exposes an Anthropic-format `/v1/messages`

If LiteLLM fronts your endpoint, `/v1/messages` generally works, accepts both
`x-api-key` and `Authorization: Bearer`, and handles tool calling. This is what
makes the Claude Code route possible at all.

### Claude Code sends real credentials to a custom base URL

With `ANTHROPIC_BASE_URL` set and `ANTHROPIC_AUTH_TOKEN` **unset**, Claude Code
sends its own OAuth token to that URL. That is what lets the router forward
Anthropic-bound traffic untouched — and it also means **any URL you point it at
receives your credentials**. Point it only at something you trust.

### A model's self-reported name means nothing

Ask "which model are you" and you may get an unrelated answer. To know what you are
actually talking to, read `PI_PROVIDER` / `PI_MODEL` in Pi, or inspect the usage and
cost fields on the response.

---

## Files

| File | Purpose |
|---|---|
| `chat_cli.py` / `chat_cli.bat` | Terminal chat |
| `chat.html` | Single-file web UI, multi-provider |
| `claude_router.py` / `claude_pick.bat` | Claude Code routing proxy |
| `examples/pi-models.json` | Pi providers and models |
| `examples/pi-settings.json` | Pi defaults |
| `examples/claude-settings-modelPicker.json` | Claude Code `/model` entries |

## License

MIT
