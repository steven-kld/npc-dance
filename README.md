# NPC Dance

A chat-driven browser automation agent. Talk to it in natural language — it controls a real Chrome browser using computer vision and remembers how to do tasks across sessions.

---

## Architecture

```
User (WebSocket chat)
    │
    ▼
agent.py ── LangGraph agent loop (Claude claude-sonnet-4-6)
    │            ├── navigate / click / type / scroll / screenshot
    │            ├── save_flow / read_flow / list_flows   ← persistent memory
    │            └── ask_user                             ← pauses, asks, resumes
    │
    ├──► Eye (eye.py) ── screenshot → Ollama qwen2.5vl:7b → element coordinates
    │
    └──► Hand (hand.py) ── Bezier mouse movement, xclip paste, keyboard

Workspace (workspace.py) ── Xvfb :2 + Chrome + x11vnc (always running)
cursor_highlight.py ── orange ring overlay that follows the automation cursor
noVNC ── browser view at http://localhost:6080/vnc.html
```

### `Workspace` ([workspace.py](workspace.py))

Starts the virtual desktop environment:
1. Xvfb on display `:2` (1920×1080)
2. Google Chrome (no URL — navigation is done by `Hand.navigate()`)
3. x11vnc on port `5900`
4. Touches `/tmp/space_ready` to signal readiness

`connect()` — lightweight function that patches pyautogui onto the already-running display `:2`. Used by `agent.py` at startup.

In Docker, `workspace.py --run` is started by `docker-start.sh` and runs as a background process for the lifetime of the container.

### `Eye` ([eye.py](eye.py))

Takes a screenshot and asks a remote vision LLM to locate a UI element by description. Returns bounding box + center coordinates.

- Model: `qwen2.5vl:7b` via Ollama (hosted on vast.ai)
- Input: natural language query e.g. `"Submit button"`
- Output: `{"bbox_2d": [...], "center": (cx, cy)}`

### `Hand` ([hand.py](hand.py))

Controls mouse and keyboard:
- `navigate(url)` — Ctrl+L → paste URL → Enter
- `move(x, y)` — quadratic Bezier curve with randomised control point
- `click(x, y)` — smooth move then click
- `click_and_type(x, y, text)` — click then paste via `xclip` + Ctrl+V
- `scroll(direction)` — up / down / left / right

### `agent.py` ([agent.py](agent.py))

LangGraph `StateGraph` with Claude claude-sonnet-4-6 as the reasoning model. Exposed as a FastAPI WebSocket server on port `8000`.

**Tools available to the agent:**

| Tool | Description |
|---|---|
| `navigate` | opens a URL |
| `click` | Eye locates element → Hand clicks |
| `type_text` | Eye locates element → Hand types |
| `scroll` | scrolls the page |
| `save_flow` | writes `flows/<name>.md` — a named procedure |
| `read_flow` | reads a saved procedure |
| `list_flows` | lists all saved procedures |
| `ask_user` | **pauses the graph**, sends question to user, resumes on reply |

**Flow memory** — procedures are stored as markdown files in `flows/`. The agent reads them before executing a task and rewrites them when the user corrects an error. The `flows/` directory is mounted as a Docker volume so memory persists across container restarts.

---

## Setup

### 1. vast.ai — Ollama vision model

Deploy a GPU instance on [vast.ai](https://vast.ai) with Ollama. Once running:

**Get the token:**
```bash
env | grep TOKEN
```

**Get the public URL** from the instance logs — look for the cloudflare tunnel line:
```
[http://localhost:21434] 2026-03-08T09:12:15Z INF |  Your quick Tunnel has been created!
# The public URL is the one printed just before or after this line
```

### 2. Environment variables

Create a `.env` file in the project root:
```env
ANTHROPIC_API_KEY=sk-ant-...
OLLAMA_URL=https://<your-tunnel>.trycloudflare.com
OLLAMA_TOKEN=<token from env | grep TOKEN>
```

### 3. Run

```bash
docker compose up --build
```

- **Browser view:** http://localhost:6080 (redirects to `vnc.html`)
- **Agent chat:** `ws://localhost:8000/ws`
- **Quick CLI test:** `python chat.py`

GPU passthrough (Intel/AMD) is enabled by default via `/dev/dri`. For NVIDIA, uncomment the block in [docker-compose.yml](docker-compose.yml).

---

## Usage

Connect to `ws://localhost:8000/ws` and send JSON messages:
```json
{"content": "go to amazon and search for mechanical keyboards"}
```

The agent replies:
```json
{"role": "assistant", "content": "Done. Found 243 results..."}
```

**Teaching the agent a flow:**
```
user: go to seller central, click Add product, fill title with "X", price with "Y", click Save
sys:  done
user: remember this as amazon_insert
sys:  Flow 'amazon_insert' saved.
```

**Running a batch:**
```
user: here are 50 products to insert: [...]
sys:  inserted 1/50... 2/50...
sys:  error on 12/50 — duplicate ASIN detected, what should I do?
user: skip duplicates and log them
sys:  ok, updating flow...
sys:  inserted 13/50...
```

---

## Notes

- Chrome profile stored at `~/.config/chrome-virtual` inside the container.
- `flows/` is mounted as a volume — procedures survive container restarts.
- No `--no-sandbox` or bot flags — Chrome runs as a non-root user with full sandbox.
