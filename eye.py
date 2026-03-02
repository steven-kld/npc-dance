import os
import cv2
import numpy as np
import pyautogui
import pytesseract
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw, ImageFont

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


class Eye:
    def __init__(self, imgs_dir: str = "imgs", log_imgs: bool = False, display: str = ""):
        self.imgs_dir = imgs_dir
        self.log_imgs = log_imgs
        self.display  = display


    def view_screen(self, coords: dict = {}, search_keyword: str = ""):
        img = np.array(pyautogui.screenshot())
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        enhanced = cv2.convertScaleAbs(enhanced, alpha=1.4, beta=-30)
        blurred = cv2.GaussianBlur(enhanced, (0, 0), 5)
        enhanced = cv2.addWeighted(enhanced, 1.8, blurred, -0.8, 0)

        # Dark text on light background
        adaptive = cv2.adaptiveThreshold(
            enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=31, C=10
        )

        # White text on dark/grey buttons
        adaptive_inv = cv2.adaptiveThreshold(
            cv2.bitwise_not(enhanced), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=31, C=10
        )

        with ThreadPoolExecutor(max_workers=3) as pool:
            f_primary  = pool.submit(self._find_text_elements, enhanced)
            f_adaptive = pool.submit(self._find_text_elements, adaptive)
            f_inv      = pool.submit(self._find_text_elements, adaptive_inv)
            primary   = f_primary.result()
            secondary = f_adaptive.result()
            tertiary  = f_inv.result()

        elements = self._merge_elements(self._merge_elements(primary, secondary), tertiary)

        n_primary = n_secondary = n_tertiary = nearest = None
        if coords:
            n_primary   = self._find_nearest(primary,   coords["x"], coords["y"])
            n_secondary = self._find_nearest(secondary, coords["x"], coords["y"])
            n_tertiary  = self._find_nearest(tertiary,  coords["x"], coords["y"])
            candidates  = [n for n in [n_primary, n_secondary, n_tertiary] if n]
            def _by_dist(e): return (e["x"] - coords["x"]) ** 2 + (e["y"] - coords["y"]) ** 2
            nearest     = min(candidates, key=_by_dist) if candidates else None
        elif search_keyword:
            n_primary   = self._search_keyword(search_keyword, primary)
            n_secondary = self._search_keyword(search_keyword, secondary)
            n_tertiary  = self._search_keyword(search_keyword, tertiary)
            candidates  = [n for n in [n_primary, n_secondary, n_tertiary] if n]
            nearest     = min(candidates, key=lambda e: len(e["text"])) if candidates else None

        if self.log_imgs:
            self._annotate(enhanced,     primary,   n_primary,   f"{self.imgs_dir}/enhanced.png")
            self._annotate(adaptive,     secondary, n_secondary, f"{self.imgs_dir}/adaptive.png")
            self._annotate(adaptive_inv, tertiary,  n_tertiary,  f"{self.imgs_dir}/adaptive_inv.png")

        return {
            "enhanced":          enhanced,
            "adaptive":          adaptive,
            "adaptive_inv":      adaptive_inv,
            "elements_enhanced": primary,
            "elements_adaptive": secondary,
            "elements_inv":      tertiary,
            "text_elements":     elements,
            "nearest_enhanced":  n_primary,
            "nearest_adaptive":  n_secondary,
            "nearest_inv":       n_tertiary,
            "nearest":           nearest,
        }

    def _find_nearest(self, elements: list[dict], x: int, y: int, min_text: int = 3, max_dist: int = 150) -> dict | None:
        valid = [e for e in elements if len(e["text"]) >= min_text]
        if not valid:
            return None
        nearest = min(valid, key=lambda e: (e["x"] - x) ** 2 + (e["y"] - y) ** 2)
        dist = ((nearest["x"] - x) ** 2 + (nearest["y"] - y) ** 2) ** 0.5
        return nearest if dist <= max_dist else None

    def _search_keyword(self, keyword: str, elements: list[dict]) -> dict | None:
        if not elements:
            return None

        keyword_lower = keyword.lower()
        exact = [el for el in elements if keyword_lower in el["text"].lower()]

        for e in exact:
            print(f"  → {repr(e['text'])} [{e['x']}, {e['y']}]")

        if exact:
            return min(exact, key=lambda e: len(e["text"]))

        return None

    def _annotate(self, img: np.ndarray, elements: list[dict], matched: dict | None, path: str) -> None:
        if len(img.shape) == 2:
            out = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        else:
            out = img.copy()

        def _is_match(el):
            return matched is not None and abs(el["x"] - matched["x"]) < 40 and abs(el["y"] - matched["y"]) < 40

        for el in elements:
            cv2.circle(out, (el["x"], el["y"]), 12, (0, 165, 255) if _is_match(el) else (0, 200, 0), -1)

        pil_img = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_img)
        try:
            font = ImageFont.truetype(_FONT_PATH, size=24)
        except OSError:
            font = ImageFont.load_default()

        for el in elements:
            draw.text((el["x"] + 16, el["y"] - 10), el["text"][:30], font=font, fill=(255, 165, 0) if _is_match(el) else (0, 200, 0))

        cv2.imwrite(path, cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR))

    def _find_text_elements(self, img: np.ndarray, config: str = "", lang: str = "rus+eng") -> list[dict]:
        base_config = "--oem 1"
        full_config = f"{base_config} {config}".strip()
        data = pytesseract.image_to_data(
            img,
            lang=lang,
            output_type=pytesseract.Output.DICT,
            config=full_config,
        )

        lines: dict = defaultdict(list)
        for i in range(len(data["text"])):
            text = data["text"][i].strip()
            conf = int(data["conf"][i])
            if text and conf > 30:
                key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
                lines[key].append({
                    "text": text,
                    "left": data["left"][i],
                    "top":  data["top"][i],
                    "w":    data["width"][i],
                    "h":    data["height"][i],
                })

        def _make_element(words: list) -> dict:
            text = " ".join(w["text"] for w in words)
            x1 = min(w["left"] for w in words)
            x2 = max(w["left"] + w["w"] for w in words)
            y1 = min(w["top"] for w in words)
            y2 = max(w["top"] + w["h"] for w in words)
            return {"text": text, "x": (x1 + x2) // 2, "y": (y1 + y2) // 2, "w": x2 - x1, "h": y2 - y1}

        elements = []
        for words in lines.values():
            words.sort(key=lambda w: w["left"])
            avg_h = sum(w["h"] for w in words) / len(words)

            gap_threshold = max(avg_h * 2, 80)
            group = [words[0]]
            for word in words[1:]:
                prev = group[-1]
                gap = word["left"] - (prev["left"] + prev["w"])
                if gap > gap_threshold:
                    elements.append(_make_element(group))
                    group = [word]
                else:
                    group.append(word)
            elements.append(_make_element(group))

        return elements

    def _merge_elements(self, primary: list[dict], secondary: list[dict], dist: int = 40) -> list[dict]:
        result = list(primary)
        for s in secondary:
            duplicate = any(
                abs(s["x"] - p["x"]) < dist and abs(s["y"] - p["y"]) < dist
                for p in result
            )
            if not duplicate:
                result.append(s)
        return result
