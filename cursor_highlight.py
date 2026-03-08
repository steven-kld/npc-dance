#!/usr/bin/env python3
"""Draws an orange ring that follows the mouse cursor on the virtual display."""
import os
import time
from Xlib import display as X11, X
from Xlib.ext import shape

DIAM = 44    # outer diameter of the ring
THICK = 3    # ring line thickness
ORANGE = 0xFF6600

# Raw shape extension constants — avoids version-specific python-xlib namespaces
_SET      = 0
_SUBTRACT = 3
_BOUNDING = 0


def _circle_mask(drawable, diameter):
    """Create a 1-bit Pixmap with a filled circle of the given diameter."""
    pm = drawable.create_pixmap(diameter, diameter, 1)
    gc_off = pm.create_gc(foreground=0, background=0)
    gc_on  = pm.create_gc(foreground=1, background=0)
    pm.fill_rectangle(gc_off, 0, 0, diameter, diameter)
    pm.fill_arc(gc_on, 0, 0, diameter, diameter, 0, 360 * 64)
    gc_off.free()
    gc_on.free()
    return pm


def run():
    dpy = X11.Display(os.environ.get("DISPLAY", ":2"))

    if not dpy.has_extension("SHAPE"):
        print("[Cursor] SHAPE extension unavailable — highlight disabled")
        return

    screen = dpy.screen()
    root   = screen.root

    win = root.create_window(
        0, 0, DIAM, DIAM, 0,
        screen.root_depth, X.InputOutput, X.CopyFromParent,
        override_redirect=True,   # always on top, no WM decoration
        event_mask=0,
        background_pixel=ORANGE,
    )

    # Carve the window into a hollow ring:
    #   outer filled circle  (full DIAM)
    #   minus inner filled circle  (DIAM - 2*THICK), centered
    outer = _circle_mask(win, DIAM)
    inner = _circle_mask(win, DIAM - THICK * 2)
    win.shape_mask(_SET,      _BOUNDING, 0,     0,     outer)
    win.shape_mask(_SUBTRACT, _BOUNDING, THICK, THICK, inner)
    outer.free()
    inner.free()

    win.map()
    dpy.flush()

    while True:
        ptr = root.query_pointer()
        win.configure(
            x=ptr.root_x - DIAM // 2,
            y=ptr.root_y - DIAM // 2,
            stack_mode=X.Above,
        )
        dpy.flush()
        time.sleep(0.033)   # ~30 fps


if __name__ == "__main__":
    while True:
        try:
            run()
        except Exception as e:
            print(f"[Cursor] crashed ({e}), restarting in 1s...")
            time.sleep(1)
