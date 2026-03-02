#!/bin/bash
set -e

# :2 — isolated virtual buffer, not connected to physical monitors (:0)
DISP=:2

echo "[Display] Starting Xvfb virtual display on $DISP (1920x1080)..."
Xvfb $DISP -screen 0 2880x1620x24 &
sleep 1

python3 -c "
import json, os
prefs_dir = os.path.expanduser('~/.config/chrome-virtual/Default')
prefs_file = os.path.join(prefs_dir, 'Preferences')
os.makedirs(prefs_dir, exist_ok=True)
prefs = {}
if os.path.exists(prefs_file):
    with open(prefs_file) as f:
        try: prefs = json.load(f)
        except: pass
prefs.setdefault('profile', {})['default_zoom_level'] = 0.4054651081081644
with open(prefs_file, 'w') as f:
    json.dump(prefs, f)
"

echo "[Chrome] Starting browser..."
DISPLAY=$DISP google-chrome \
    --window-size=1920,1080 \
    --window-position=0,0 \
    --force-device-scale-factor=1.5 \
    --user-data-dir=$HOME/.config/chrome-virtual \
    > /dev/null 2>&1 &
sleep 3

echo "[VNC] Starting x11vnc on port 5900..."
x11vnc -display $DISP -forever -nopw -quiet -scale 0.5 &
sleep 1

echo "[VNC] Opening viewer window..."
vncviewer localhost:5900 &

echo ""
echo "Done."
echo ""
echo "Run scripts:"
echo "  DISPLAY=$DISP python run.py"
echo "  DISPLAY=$DISP python agent.py"
echo "  DISPLAY=$DISP python test.py"
echo ""
echo "Stop: ./kill.sh"
