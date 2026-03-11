import base64
import os
import time
import json
from io import BytesIO
from PIL import Image
from openai import OpenAI

BEDROCK_BASE_URL = "https://bedrock-mantle.us-east-1.api.aws/v1"
BEDROCK_MODEL = "qwen.qwen3-vl-235b-a22b-instruct"

SYSTEM_PROMPT = """You are a UI element detector. Analyze the screenshot and locate the requested element.
Respond ONLY with a valid JSON object, no explanation, no markdown, no backticks.
Use exactly one of these 2 formats:
1. Element clearly found:
{"bbox_2d": [x1, y1, x2, y2], "label": "element name"}
2. Not found:
{"info": <str>}"""


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


class Eye:
    def __init__(
        self,
        api_key: str,
        model: str = BEDROCK_MODEL,
        system_prompt: str = SYSTEM_PROMPT,
    ):
        self.model = model
        self.system_prompt = system_prompt
        self.client = OpenAI(base_url=BEDROCK_BASE_URL, api_key=api_key)

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
        print("[Eye] Bedrock Eye ready (no warmup needed)")

    def locate(self, query: str) -> dict:
        print(f"[Eye] locate: '{query}'")
        t0 = time.time()

        image_b64, w, h, real_w, real_h = self._screenshot_b64()

        print(f"[Eye] calling Bedrock API ({w}x{h} px)...")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                        {
                            "type": "text",
                            "text": f"The image is {w}x{h} pixels. Locate: {query}",
                        },
                    ],
                },
            ],
        )

        raw = response.choices[0].message.content
        print(f"[Eye] response: {raw} ({time.time() - t0:.2f}s)")

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"error": raw}

        if "bbox_2d" in parsed:
            x1, y1, x2, y2 = parsed["bbox_2d"]
            # Qwen-VL returns coords in 0-1000 normalized space, scale to real pixels
            x1 = int(x1 / 1000 * real_w)
            y1 = int(y1 / 1000 * real_h)
            x2 = int(x2 / 1000 * real_w)
            y2 = int(y2 / 1000 * real_h)
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            print(f"[Eye] found '{parsed.get('label','')}' center=({cx},{cy})")
            return {**parsed, "bbox_2d": [x1, y1, x2, y2], "center": (cx, cy)}

        print(f"[Eye] not found: {parsed}")
        return parsed
