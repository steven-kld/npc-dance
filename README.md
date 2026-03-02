# NPC Dance

A screen automation toolkit that uses computer vision and OCR to read the screen and control mouse/keyboard inputs. Designed to run against a live X11 display (real or virtual via Xvfb).

---

## Architecture

The project has four classes that work as a pipeline:

```
Workspace ── starts Xvfb + Chrome + VNC, sets DISPLAY, patches pyautogui
    │
    ▼
Eye ──── takes screenshot, preprocesses image, runs OCR → list of text elements
    │
    └──► Hand ──── moves mouse along a Bezier curve, clicks, types via clipboard
    │
    └──► Memory ─── listens for real mouse clicks via X11 RECORD, logs to JSON
                    optionally calls Eye to identify what was clicked
```

### `Workspace` ([workspace.py](workspace.py))

Manages the virtual desktop environment. On construction it spawns a child process of itself (`workspace.py --run`) which:

1. Starts **Xvfb** on display `:2` (2880×1620)
2. Configures Chrome preferences (zoom level)
3. Launches **Google Chrome** against `:2`, optionally at a given URL
4. Starts **x11vnc** on port `5900`
5. Opens **vncviewer** pointed at `localhost:5900`
6. Touches `/tmp/space_ready` to signal readiness

The parent constructor blocks until `/tmp/space_ready` appears, then sets `os.environ["DISPLAY"] = ":2"` and patches `pyautogui`'s internal Xlib display handle so subsequent Eye/Hand calls work against `:2` automatically.

`wait()` blocks until the subprocess exits (Chrome closed, Ctrl+C, etc.) and handles `KeyboardInterrupt` by terminating the subprocess.

This replaces `legacy_start.sh` / `legacy_kill.sh` entirely — no shell scripts needed.

**Requires:** `Xvfb`, `google-chrome`, `x11vnc`, `tigervnc-viewer`.

### `Eye` ([eye.py](eye.py))

Captures the screen with `pyautogui.screenshot()` and finds all visible text elements using Tesseract OCR. To improve accuracy on varied UI backgrounds it runs three parallel OCR passes on different image variants:

- **enhanced** – contrast-boosted grayscale (CLAHE + unsharp mask)
- **adaptive** – adaptive threshold for dark text on light backgrounds
- **adaptive_inv** – inverted adaptive threshold for white text on dark/colored buttons

Results from all three passes are deduplicated by proximity and merged into a single element list. Each element is a dict: `{"text": str, "x": int, "y": int, "w": int, "h": int}` where `x`/`y` is the center of the text bounding box.

`view_screen()` accepts either:
- `coords={"x": …, "y": …}` – returns the nearest text element to those coordinates
- `search_keyword="…"` – returns the best-matching element containing that substring

When `log_imgs=True`, annotated debug images are saved to `imgs/` for each OCR pass.

**Requires:** `tesseract-ocr`, `tesseract-ocr-eng`, `tesseract-ocr-rus` (language pack), DejaVu fonts, active `DISPLAY`.

### `Hand` ([hand.py](hand.py))

Controls the mouse and keyboard via `pyautogui`. Mouse movement uses a quadratic Bezier curve with a randomised control point and per-step delays to produce human-like motion.

Methods:
- `move(x, y)` – smooth Bezier move to `(x, y)`
- `click(x, y)` – move then click
- `paste(text)` – write text to clipboard via `xclip`, then `Ctrl+V`
- `click_and_type(x, y, text)` – click then paste text
- `scroll(direction, fraction)` – scroll by a fraction of the screen height/width

`pyautogui.FAILSAFE = True` is set: moving the mouse to the top-left corner raises an exception and aborts execution.

**Requires:** `xclip`, active `DISPLAY`.

### `Memory` ([memory.py](memory.py))

Records human mouse clicks on an X11 display using the **X11 RECORD extension** (`python-xlib`). For each click it logs coordinates, button, timestamp, and optionally the nearest OCR text element (via an `on_click` callback passed at construction).

Each click is handled in a background thread so OCR does not block the event stream. The running log is written to `record/log.json` after every click, sorted by click order.

Call `memory.record()` to start listening; press `Ctrl+C` to stop.

**Requires:** `python-xlib`, X11 display with RECORD extension enabled.

---

## Prerequisites

### System packages

```bash
sudo apt install \
  xvfb \
  x11vnc \
  tigervnc-viewer \
  tesseract-ocr \
  tesseract-ocr-eng \
  tesseract-ocr-rus \
  xclip \
  fonts-dejavu \
  python3-venv
```

Chrome (if not already installed):
```bash
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install ./google-chrome-stable_current_amd64.deb
```

### Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Python packages installed by `requirements.txt`:

| Package | Used by |
|---|---|
| `opencv-python` | Eye — image preprocessing |
| `numpy` | Eye — array operations |
| `pytesseract` | Eye — Tesseract OCR wrapper |
| `pyautogui` | Eye (screenshot), Hand (mouse/keyboard) |
| `python-xlib` | Memory — X11 RECORD; Workspace — display patching |
| `Pillow` | Eye — annotated debug image output |

---

## Usage

`main.py` shows a minimal example: `Workspace` sets everything up, `Eye` finds UI elements by keyword, `Hand` interacts with them.

```bash
source .venv/bin/activate
python main.py
```

No `DISPLAY` prefix needed — `Workspace.__init__` sets it automatically.

To record human interactions to `record/log.json`:

```python
from workspace import Workspace
from eye import Eye
from memory import Memory

workspace = Workspace(url="https://example.com")
eye = Eye(log_imgs=True, display=":2")
memory = Memory(on_click=lambda x, y: eye.view_screen(coords={"x": x, "y": y})["nearest"])
memory.record()   # blocks until Ctrl+C
workspace.wait()
```

---

## Notes

- Virtual display runs on `:2` to avoid conflicts with your main display (`:0`).
- Chrome profile is stored in `~/.config/chrome-virtual` (separate from your main profile).
- VNC viewer opens automatically at `localhost:5900` (no password).
- Debug OCR images are saved to `imgs/` when `log_imgs=True` (gitignored).
- Click logs are saved to `record/log.json` (gitignored).
- No root/sudo required after the initial `apt install`.
- `legacy_start.sh` / `legacy_kill.sh` are the old shell-script equivalents of `Workspace` — kept for reference.
