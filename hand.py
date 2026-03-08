import random
import time
import subprocess
import pyautogui

pyautogui.FAILSAFE = True


class Hand:
    def move(self, x: int, y: int, steps: int = 13) -> None:
        start_x, start_y = pyautogui.position()
        cx = (start_x + x) / 2 + random.randint(-80, 80)
        cy = (start_y + y) / 2 + random.randint(-80, 80)
        for i in range(steps + 1):
            t = i / steps
            bx = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * cx + t ** 2 * x
            by = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * cy + t ** 2 * y
            pyautogui.moveTo(int(bx), int(by))
            time.sleep(0.001)

    def click(self, x: int, y: int) -> None:
        self.move(x, y)
        time.sleep(0.01)
        pyautogui.click()

    def paste(self, text: str) -> None:
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
        time.sleep(0.02)
        pyautogui.hotkey("ctrl", "v")

    def click_and_type(self, x: int, y: int, text: str) -> None:
        self.click(x, y)
        time.sleep(0.2)
        self.paste(text)

    def navigate(self, url: str) -> None:
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.3)
        self.paste(url)
        time.sleep(0.1)
        pyautogui.press("enter")
        time.sleep(2)

    def scroll(self, direction: str = "down", fraction: float = 0.05) -> None:
        w, h = pyautogui.size()
        pyautogui.moveTo(w // 2, h // 2)
        time.sleep(0.02)
        if direction in ("down", "up"):
            clicks = max(1, int(h * fraction / 30))
            pyautogui.scroll(-clicks if direction == "down" else clicks)
        else:
            clicks = max(1, int(w * fraction / 30))
            pyautogui.hscroll(-clicks if direction == "right" else clicks)
        time.sleep(0.2)