import os
import json
import struct
import time
import threading

from Xlib import X, display as xdisplay
from Xlib.ext import record


class Memory:
    def __init__(self, on_click=None, record_dir: str = "record", display: str = ":2"):
        self.record_dir = record_dir
        self.display    = display
        self._on_click  = on_click  # optional: fn(x, y) -> dict | None
        self._log       = []
        self._click_num = 0
        self._lock      = threading.Lock()

    def record(self) -> None:
        os.makedirs(self.record_dir, exist_ok=True)

        d = xdisplay.Display(self.display)
        if not d.has_extension("RECORD"):
            raise RuntimeError("X11 RECORD extension not available")

        ctx = d.record_create_context(
            0,
            [record.AllClients],
            [{
                "core_requests":    (0, 0),
                "core_replies":     (0, 0),
                "ext_requests":     (0, 0, 0, 0),
                "ext_replies":      (0, 0, 0, 0),
                "delivered_events": (0, 0),
                "device_events":    (X.ButtonPressMask, X.ButtonPressMask),
                "errors":           (0, 0),
                "client_started":   False,
                "client_died":      False,
            }],
        )

        print(f"Recording clicks on {self.display}... Ctrl+C to stop.")
        try:
            d.record_enable_context(ctx, self._handler)
        except KeyboardInterrupt:
            pass
        finally:
            d.record_free_context(ctx)
            print(f"\nStopped. Recorded: {self._click_num} clicks")

    def _handler(self, reply) -> None:
        if reply.category != record.FromServer:
            return
        data = reply.data
        while len(data) >= 32:
            if (data[0] & 0x7f) == X.ButtonPress:
                button = data[1]
                x, y   = struct.unpack_from("<hh", data, 20)
                ts = time.time()
                n  = self._next_n()
                threading.Thread(target=self._handle_click, args=(n, x, y, button, ts), daemon=True).start()
            data = data[32:]

    def _next_n(self) -> int:
        with self._lock:
            self._click_num += 1
            return self._click_num

    def _handle_click(self, n: int, x: int, y: int, button: int, ts: float) -> None:
        nearest = self._on_click(x, y) if self._on_click else None

        entry = {
            "n":        n,
            "x":        x,
            "y":        y,
            "button":   button,
            "ts":       ts,
            "ocr_text": nearest["text"] if nearest else None,
            "ocr_x":    nearest["x"]    if nearest else None,
            "ocr_y":    nearest["y"]    if nearest else None,
        }

        with self._lock:
            self._log.append(entry)
            self._log.sort(key=lambda e: e["n"])
            with open(f"{self.record_dir}/log.json", "w") as f:
                json.dump(self._log, f, indent=2, ensure_ascii=False)

        ocr_info = f'"{nearest["text"]}"' if nearest else "—"
        print(f"  [{n:03d}] ({x}, {y})  → {ocr_info}")

