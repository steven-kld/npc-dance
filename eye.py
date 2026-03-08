import base64
import os
import time
import requests
import json
from io import BytesIO
from PIL import Image


def take_screenshot() -> Image.Image:
    """Capture the X display directly via Xlib — works with Xvfb, no gnome-screenshot needed."""
    from Xlib import display as _Xdisplay, X as _X
    d = _Xdisplay.Display(os.environ.get("DISPLAY", ":2"))
    root = d.screen().root
    geom = root.get_geometry()
    raw = root.get_image(0, 0, geom.width, geom.height, _X.ZPixmap, 0xFFFFFFFF)
    img = Image.frombuffer("RGBA", (geom.width, geom.height), raw.data, "raw", "BGRA", 0, 1)
    d.close()
    return img.convert("RGB")

SYSTEM_PROMPT = """You are a UI element detector. Analyze the screenshot and locate the requested element.
Respond ONLY with a valid JSON object, no explanation, no markdown, no backticks.
Use exactly one of these 2 formats:
1. Element clearly found:
{"bbox_2d": [x1, y1, x2, y2], "label": "element name"}
2. Not found:
{"info": <str>}"""


class Eye:
    def __init__(
        self,
        ollama_url: str,
        token: str,
        model: str = "qwen2.5vl:7b",
        system_prompt: str = SYSTEM_PROMPT,
        timeout: int = 600,
    ):
        self.ollama_url = ollama_url
        self.token = token
        self.model = model
        self.system_prompt = system_prompt
        self.timeout = timeout

    def _screenshot_b64(self) -> tuple[str, int, int, int, int]:
        img = take_screenshot()
        real_w, real_h = img.size
        target_w, target_h = int(real_w / 1.5), int(real_h / 1.5)
        img = img.resize((target_w, target_h))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=55)
        b64 = base64.b64encode(buf.getvalue()).decode()
        print(f"[Eye] screenshot {real_w}x{real_h} → {target_w}x{target_h} ({len(b64)//1024}kb)")
        return b64, target_w, target_h, real_w, real_h

    def warmup(self) -> None:
        print("[Eye] warming up model...")
        t0 = time.time()
        response = requests.post(
            f"{self.ollama_url}/api/chat",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Authorization": f"Bearer {self.token}",
            },
            json={
                "model": self.model,
                "stream": False,
                "messages": [{"role": "user", "content": "hi", "images": []}],
            },
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise RuntimeError(f"API error {response.status_code}: {response.text}")

        print(f"[Eye] model ready ({time.time() - t0:.2f}s)")

    def locate(self, query: str) -> dict:
        print(f"[Eye] locate: '{query}'")
        t0 = time.time()

        image_b64, w, h, real_w, real_h = self._screenshot_b64()
        scale_x = real_w / w
        scale_y = real_h / h

        print(f"[Eye] calling API ({w}*{h} px)...")
        response = requests.post(
            f"{self.ollama_url}/api/chat",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Authorization": f"Bearer {self.token}",
            },
            json={
                "model": self.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {
                        "role": "user",
                        "content": f"The image is {w}*{h} pixels. Locate: {query}",
                        "images": [image_b64],
                    },
                ],
            },
            timeout=self.timeout,
        )

        if response.status_code != 200:
            raise RuntimeError(f"API error {response.status_code}: {response.text}")

        raw = response.json()["message"]["content"]
        print(f"[Eye] response: {raw} ({time.time() - t0:.2f}s)")

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"error": raw}

        if "bbox_2d" in parsed:
            x1, y1, x2, y2 = parsed["bbox_2d"]
            x1, x2 = int(x1 * scale_x), int(x2 * scale_x)
            y1, y2 = int(y1 * scale_y), int(y2 * scale_y)
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            print(f"[Eye] found '{parsed.get('label','')}' center=({cx},{cy})")
            return {**parsed, "bbox_2d": [x1, y1, x2, y2], "center": (cx, cy)}

        print(f"[Eye] not found: {parsed}")
        return parsed