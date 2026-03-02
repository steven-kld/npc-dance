import json
import os
import subprocess
import sys
import time

DISP = ":2"
_READY = "/tmp/space_ready"


class Workspace:
    def __init__(self, url: str = ""):
        if os.path.exists(_READY):
            os.remove(_READY)

        args = [sys.executable, __file__, "--run"]
        if url:
            args += ["--url", url]
        self._proc = subprocess.Popen(
            args,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )

        while not os.path.exists(_READY):
            time.sleep(0.2)

        os.environ["DISPLAY"] = DISP

        try:
            import pyautogui._pyautogui_x11 as _pag
            from Xlib.display import Display as _D
            _pag._display = _D(DISP)
            _pag._root = _pag._display.screen().root
        except Exception:
            pass

    def wait(self):
        try:
            self._proc.wait()
        except KeyboardInterrupt:
            self._proc.terminate()
            self._proc.wait()


def _run():
    procs = []

    def stop():
        for p in procs:
            p.terminate()
        subprocess.run(["pkill", "-f", f"Xvfb {DISP}"],    capture_output=True)
        subprocess.run(["pkill", "-f", "chrome-virtual"], capture_output=True)
        subprocess.run(["pkill", "-f", "x11vnc"],         capture_output=True)
        subprocess.run(["pkill", "-f", "vncviewer"],      capture_output=True)

    print(f"[Display] Starting Xvfb on {DISP}...")
    procs.append(subprocess.Popen(["Xvfb", DISP, "-screen", "0", "2880x1620x24"]))
    time.sleep(1)

    prefs_dir = os.path.expanduser("~/.config/chrome-virtual/Default")
    prefs_file = os.path.join(prefs_dir, "Preferences")
    os.makedirs(prefs_dir, exist_ok=True)
    prefs = {}
    if os.path.exists(prefs_file):
        with open(prefs_file) as f:
            try:
                prefs = json.load(f)
            except Exception:
                pass
    prefs.setdefault("profile", {})["default_zoom_level"] = 0.4054651081081644
    with open(prefs_file, "w") as f:
        json.dump(prefs, f)

    url = sys.argv[sys.argv.index("--url") + 1] if "--url" in sys.argv else ""

    print("[Chrome] Starting browser...")
    env = {**os.environ, "DISPLAY": DISP}
    chrome_cmd = ["google-chrome",
                  "--window-size=1920,1080",
                  "--window-position=0,0",
                  "--force-device-scale-factor=1.5",
                  f"--user-data-dir={os.path.expanduser('~/.config/chrome-virtual')}"]
    if url:
        chrome_cmd.append(url)
    procs.append(subprocess.Popen(
        chrome_cmd,
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ))
    time.sleep(3)

    print("[VNC] Starting x11vnc on port 5900...")
    procs.append(subprocess.Popen(
        ["x11vnc", "-display", DISP, "-forever", "-nopw", "-quiet", "-scale", "0.5"]
    ))
    time.sleep(1)

    print("[VNC] Opening viewer...")
    procs.append(subprocess.Popen(["vncviewer", "localhost:5900"]))
    open(_READY, "w").close()

    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        stop()


if __name__ == "__main__" and "--run" in sys.argv:
    _run()
