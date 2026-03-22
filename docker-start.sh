#!/bin/bash
set -e

# noVNC: proxies VNC port 5900 → WebSocket 6080 for browser access
websockify --web /usr/share/novnc 6080 localhost:5900 &

# Start virtual desktop infrastructure (Xvfb + Chrome + x11vnc)
python3 automation/workspace.py --run &

# Wait for display to be ready (workspace.py touches /tmp/space_ready when done)
echo "[Docker] Waiting for display..."
while [ ! -f /tmp/space_ready ]; do sleep 0.2; done
echo "[Docker] Display ready."

# Start cursor highlight overlay (orange ring that follows the automation cursor)
python3 automation/cursor_highlight.py &

# Start the agent API server (main process — keeps container alive)
exec python3 server.py
