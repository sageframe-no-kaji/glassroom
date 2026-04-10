#!/bin/bash
# Glassroom container entrypoint
# Starts the virtual display stack (for headed Playwright login),
# then starts the Flask app in the foreground.
set -e

# ---- Virtual framebuffer ------------------------------------------------
# Required so Playwright can open a headed browser during the login step.
Xvfb :99 -screen 0 1280x900x24 -ac +extension GLX +render -noreset &
sleep 1

# VNC server (no password — only accessible from the container host)
x11vnc -display :99 -nopw -forever -shared -quiet &

# noVNC — web-based VNC viewer at http://localhost:6080/vnc.html
websockify --web=/usr/share/novnc/ 6080 localhost:5900 &

# ---- Flask app ----------------------------------------------------------
exec python src/app.py
