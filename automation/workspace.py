import json
import os
import subprocess
import sys
import time

DISP = ":2"
PROFILE_DIR = os.path.expanduser("~/.config/chrome-virtual")
_READY = "/tmp/space_ready"


def connect():
    """Patch pyautogui to use the already-running virtual display :2."""
    os.environ["DISPLAY"] = DISP
    try:
        import pyautogui._pyautogui_x11 as _pag
        from Xlib.display import Display as _D
        _pag._display = _D(DISP)
        _pag._root = _pag._display.screen().root
    except Exception:
        pass


def _run():
    procs = []

    def stop():
        for p in procs:
            p.terminate()
        subprocess.run(["pkill", "-f", f"user-data-dir={PROFILE_DIR}"], capture_output=True)
        subprocess.run(["pkill", "-f", f"Xvfb {DISP}"],                 capture_output=True)
        subprocess.run(["pkill", "-f", "x11vnc"],                       capture_output=True)

    subprocess.run(["pkill", "-f", f"Xvfb {DISP}"], capture_output=True)
    subprocess.run(["pkill", "-f", f"user-data-dir={PROFILE_DIR}"], capture_output=True)
    subprocess.run(["pkill", "-f", "x11vnc"],   capture_output=True)
    time.sleep(0.5)
    lock = f"/tmp/.X{DISP.replace(':', '')}-lock"
    if os.path.exists(lock):
        os.remove(lock)
        print(f"[Display] Removed stale lock {lock}")
    print(f"[Display] Starting Xvfb on {DISP}...")
    procs.append(subprocess.Popen(["Xvfb", DISP, "-screen", "0", "1920x1080x24"]))
    time.sleep(1)

    prefs_path = os.path.join(PROFILE_DIR, "Default", "Preferences")
    os.makedirs(os.path.dirname(prefs_path), exist_ok=True)
    prefs = {}
    if os.path.exists(prefs_path):
        try:
            with open(prefs_path) as f:
                prefs = json.load(f)
        except Exception:
            pass
    prefs.setdefault("profile", {})["default_zoom_level"] = 0.0
    with open(prefs_path, "w") as f:
        json.dump(prefs, f)

    print("[Chrome] Starting browser...")
    procs.append(subprocess.Popen(
        [
            "google-chrome",
            "--window-size=1920,1080",
            "--window-position=0,0",
            "--no-restore-session-state",
            "--disable-session-crashed-bubble",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--disable-dev-shm-usage",   # avoid /dev/shm exhaustion → "Aw, Snap!" crashes
            "--no-first-run",
            f"--user-data-dir={PROFILE_DIR}",
        ],
        env={**os.environ, "DISPLAY": DISP},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ))
    time.sleep(3)

    print("[VNC] Starting x11vnc on port 5900...")
    procs.append(subprocess.Popen(
        ["x11vnc", "-display", DISP, "-forever", "-nopw", "-quiet"]
    ))
    time.sleep(1)

    open(_READY, "w").close()
    print("[Workspace] Ready.")

    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        stop()


if __name__ == "__main__" and "--run" in sys.argv:
    _run()
