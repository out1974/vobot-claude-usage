#!/bin/bash
# Double-click this file in Finder to start the Claude Dock companion on your Mac.
# A Terminal window opens and shows the server's LAN URL. Leave it open while you
# want the dock to update. Close the window (or press Ctrl+C) to stop it.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$DIR" || exit 1
echo "Starting Claude Dock companion…  (leave this window open; Ctrl+C to stop)"
echo
exec /usr/bin/python3 claude_dock_server.py
