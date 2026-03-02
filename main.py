import time

from workspace import Workspace
from eye import Eye
from hand import Hand
from memory import Memory


_eye = Eye(log_imgs=True, display=":2")
_hand = Hand()
_memory = Memory(on_click=lambda x, y: _eye.view_screen(coords={"x": x, "y": y})["nearest"])


def search_keyword(keyword: str = "") -> dict | None:
    scan = _eye.view_screen(search_keyword=keyword)
    return scan["nearest"]


def search_nearest(x: int, y: int) -> dict | None:
    scan = _eye.view_screen(coords={"x": x, "y": y})
    return scan["nearest"]


if __name__ == "__main__":
    _workspace = Workspace(url="https://www.wikipedia.org/")

    try:
        # Execute
        nearest = _eye.view_screen(search_keyword="English")["nearest"]
        _hand.click(nearest["x"], nearest["y"])
        time.sleep(3)

        nearest = _eye.view_screen(search_keyword="Search Wikipedia")["nearest"]
        _hand.click_and_type(nearest["x"], nearest["y"], "npc")

        nearest = _eye.view_screen(search_keyword="Search")["nearest"]
        _hand.click(nearest["x"], nearest["y"])

        _workspace.wait()

    # try:
    #     # Memorize
    #     _memory.record()
    #     _workspace.wait()

    finally:
        _workspace._proc.terminate()