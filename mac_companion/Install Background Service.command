#!/bin/bash
# Double-click ONCE to install the Claude Dock companion as a background service.
# It auto-starts at login and keeps running (no window needed).
#
# Note: macOS blocks background (launchd) services from reading ~/Documents, so we
# copy the server to ~/.claude-dock (an unprotected location) and run it from there.
# To remove it later, run "Uninstall Background Service.command".

DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SRC="$DIR/claude_dock_server.py"
APPDIR="$HOME/.claude-dock"
PLIST="$HOME/Library/LaunchAgents/com.vobot.claude-dock.plist"

mkdir -p "$APPDIR" "$HOME/Library/LaunchAgents" || { echo "could not create folders"; read -n 1 -s; exit 1; }
cp "$SRC" "$APPDIR/claude_dock_server.py" || { echo "could not copy server from: $SRC"; read -n 1 -s; exit 1; }

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.vobot.claude-dock</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>${APPDIR}/claude_dock_server.py</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>${APPDIR}/companion.out.log</string>
    <key>StandardErrorPath</key><string>${APPDIR}/companion.err.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"

IP="$(ipconfig getifaddr en0 2>/dev/null)"; [ -z "$IP" ] && IP="$(ipconfig getifaddr en1 2>/dev/null)"; [ -z "$IP" ] && IP="<your-mac-ip>"

echo "Installed to $APPDIR. Waiting for the companion to come up…"
ok=""
for i in $(seq 1 20); do
    if curl -fs "http://127.0.0.1:8787/" >/dev/null 2>&1; then ok=1; break; fi
    sleep 1
done
echo
if [ -n "$ok" ]; then
    echo "✅ Companion is running in the background (auto-starts at login)."
    echo "   Helper URL for the dock:  http://$IP:8787/usage"
    echo "   You can close this window now."
else
    echo "⚠️  Still not reachable. See: $APPDIR/companion.err.log"
fi
echo
echo "Press any key to close."
read -n 1 -s
