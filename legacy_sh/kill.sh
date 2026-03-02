#!/bin/bash

pkill -f "Xvfb :2"         2>/dev/null || true
pkill -f "chrome-virtual"  2>/dev/null || true
pkill -f "x11vnc"          2>/dev/null || true
pkill -f "vncviewer"       2>/dev/null || true
