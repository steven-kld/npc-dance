import time
from eye import Eye
from hand import Hand
from flow_instruction import FlowInstruction


class FlowCall:
    def __init__(self, instruction: FlowInstruction, eye: Eye, hand: Hand):
        self.instruction = instruction
        self.eye = eye
        self.hand = hand

    def run(self):
        for step in self.instruction.steps:
            self._run_step(step)

    def _run_step(self, step: dict):
        t = step["type"]

        if t == "navigate":
            self.hand.navigate(step["url"])

        elif t == "click":
            result = self.eye.locate(step["search_description"])
            if "center" not in result:
                raise RuntimeError(f"Could not locate: {step['search_description']}")
            self.hand.click(*result["center"])

        elif t == "click and paste":
            result = self.eye.locate(step["search_description"])
            if "center" not in result:
                raise RuntimeError(f"Could not locate: {step['search_description']}")
            self.hand.click_and_type(*result["center"], step["input_text"])

        elif t == "locate":
            result = self.eye.locate(step["search_description"])
            if "center" not in result:
                raise RuntimeError(f"Could not locate: {step['search_description']}")

        elif t == "scroll":
            self.hand.scroll()

        elif t == "press enter":
            import pyautogui
            pyautogui.press("enter")

        elif t == "wait sec":
            time.sleep(step["seconds"])

        elif t == "wait until locate":
            timeout = step.get("timeout_sec", 10)
            deadline = time.time() + timeout
            while time.time() < deadline:
                result = self.eye.locate(step["search_description"])
                if "center" in result:
                    return
                time.sleep(1)
            raise RuntimeError(f"Timeout waiting for: {step['search_description']}")

        else:
            raise ValueError(f"Unknown step type: {t}")
