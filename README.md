# NPC

A flow-driven browser automation agent. Describe what you want to do in natural language - it finds the right flow, parses your data, shows you a preview, and executes it in a real Chrome browser using computer vision.

---

## How it works

```
User (WebSocket chat / make chat)
    │
    ▼
agent.py - LangGraph agent (DeepSeek-V3.1 via Together AI)
    │   ├── find_flow      - matches user intent to a flow in flows.json
    │   ├── prepare_flow   - parses input, shows field preview, flags missing data
    │   └── run_flow       - excutes on user confirmation
    │
    ├──► Eye (eye.py) - screenshot → Qwen3-VL-8B (Together AI) → element coordinates
    │
    └──► Hand (hand.py) - Bezier mouse movement, xclip paste, keyboard

Workspace (workspace.py) - Xvfb :2 + Chrome + x11vnc
noVNC - watch the browser at http://localhost:6080
```

---

## Components

### `agent.py`

FastAPI app with a LangGraph agent loop. Exposed as:
- `ws://localhost:8000/ws` - WebSocket chat
- `http://localhost:8000/log` - live agent log
- `http://localhost:8000/img-log` - last Eye screenshot with bbox overlay

**Agent tools:**

| Tool | What it does |
|---|---|
| `find_flow` | LLM-matches the user's message to a flow in `flows.json` |
| `prepare_flow` | Parses user input into field values, renders a preview table, flags `⚠ missing` required fields |
| `run_flow` | Same parse step, then executes each record sequentially via `FlowCall` |

**Conversation flow:**
1. User describes what they want → `find_flow` picks a flow
2. User provides data → `prepare_flow` shows preview
3. User fills missing fields → `prepare_flow` again with corrections
4. User says "go" → `run_flow` executes

Multiple records are supported - send them one per line, all in one message.

### `flow_instruction.py`

Takes a flow definition + raw user input string, calls DeepSeek to extract field values into the flow's `input_schema`, and returns a `FlowInstruction` with rendered steps ready to execute.

### `flow_call.py`

Executes a `FlowInstruction` step by step using `Eye` and `Hand`.

**Step types:**

| type | fields | description |
|---|---|---|
| `navigate` | `url` | Navigate browser to URL |
| `click` | `search_description` | Locate element visually and click |
| `click and paste` | `search_description`, `input_text` | Click field then paste text |
| `locate` | `search_description` | Assert element is visible, no click |
| `scroll` | - | Scroll down |
| `press enter` | - | Press Enter |
| `wait sec` | `seconds` | Sleep N seconds |
| `wait until locate` | `search_description`, `timeout_sec` | Poll until element found or timeout |

`input_text` supports `{key.value}` placeholders - substituted with parsed field values at runtime.

### `eye.py`

Takes a screenshot of the virtual display, sends it to `Qwen3-VL-8B` on Together AI, and returns the bounding box and center pixel coordinates of the requested UI element.

- Coordinates from the model are in 0–1000 normalized space, scaled to real screen pixels
- Saves the annotated result to `/tmp/result.png` (viewable at `/img-log`)

### `hand.py`

Controls mouse and keyboard on the virtual display:
- `navigate(url)` - Ctrl+L → paste URL → Enter
- `move(x, y)` - quadratic Bezier curve with randomised control point
- `click(x, y)` - smooth move then click
- `click_and_type(x, y, text)` - click then paste via `xclip` + Ctrl+V
- `scroll(direction)` - up / down / left / right

### `workspace.py`

Starts the virtual desktop environment:
1. Xvfb on display `:2` (1920×1080)
2. Google Chrome
3. x11vnc on port `5900`

`connect()` patches pyautogui onto display `:2`. Called by `agent.py` at startup.

In Docker, `workspace.py --run` runs as a background process for the lifetime of the container.

### `flows.json`

Defines available flows. Each flow has:

```json
{
  "id": "unique_id",
  "name": "Human-readable name",
  "description": "What this flow does - used by find_flow for matching",
  "input_schema": [
    { "key": "field_key", "description": "Human label shown to user" },
    { "key": "optional_field", "description": "...", "optional": true }
  ],
  "steps": [
    { "type": "navigate", "url": "https://..." },
    { "type": "click and paste", "search_description": "Amount field", "input_text": "{field_key.value}" }
  ]
}
```

---

## Setup

### 1. Environment

Create a `.env` file in the project root:

```env
TOGETHER_AI_API_KEY=your_key_here
```

### 2. Run

```bash
make up
```

- **Browser view:** http://localhost:6080
- **Agent log:** http://localhost:8000/log

### 3. Chat

```bash
make chat
```

Connects a terminal WebSocket client to `ws://localhost:8000/ws`.

---

## Notes

- Chrome profile stored at `~/.config/chrome-virtual` inside the container.
- `flows/` is mounted as a Docker volume - flow definitions survive container restarts.
- `agent.log` and `result.jpg` are mounted to the host for easy inspection.
- For NVIDIA GPU passthrough, uncomment the block in `docker-compose.yml`.
