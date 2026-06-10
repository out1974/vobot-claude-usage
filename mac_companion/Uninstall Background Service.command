#!/bin/bash
# Double-click to remove the background companion service.
DEST="$HOME/Library/LaunchAgents/com.vobot.claude-dock.plist"
launchctl unload "$DEST" 2>/dev/null || true
rm -f "$DEST"
echo "✅ Removed the background service (the dock's Claude Code panel will stop updating)."
echo
echo "Press any key to close."
read -n 1 -s
