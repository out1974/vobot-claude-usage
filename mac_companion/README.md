# Claude Dock – Mac companion (Claude Code / Cowork usage)

`claude_dock_server.py` is a tiny local server that powers the **Claude Code** panel
on the Vobot Mini Dock.

**Why it's needed:** Claude Code / Cowork usage runs through your **subscription plan**,
not the metered API, so it does **not** appear in the Anthropic Usage & Cost Admin API.
The token counts *are* written to local transcript logs under `~/.claude/projects/`.
This server reads those logs, sums tokens per day, and serves them as JSON on your LAN
so the dock can display them.

- Standard library only — **no installs** (uses the `python3` already on macOS).
- Reads **only token counts + timestamps**, never conversation content.
- Serves on your LAN only; nothing is sent to the cloud.

---

## 1. Quick test (no server)

```bash
cd "/path/to/vobot-claude-usage/mac_companion"
python3 claude_dock_server.py --print 7
```

You should see a JSON payload with per-day token totals. If today shows tokens, it works.

## 2. Run the server

```bash
python3 claude_dock_server.py
```

It prints something like:

```
Claude Dock companion running.
  Local:   http://127.0.0.1:8787/usage
  On LAN:  http://192.168.1.50:8787/usage   <-- use THIS in the dock settings
```

Note the **On LAN** URL — you'll paste it into the dock app settings as
**“Claude Code helper URL”**. Custom port: `python3 claude_dock_server.py --port 9000`.

> Find your Mac's IP manually if needed: `ipconfig getifaddr en0` (Wi-Fi) or
> System Settings → Wi-Fi → Details → IP address.

> **macOS firewall:** the first time, macOS may ask whether `python3` may accept
> incoming connections — **Allow** it, otherwise the dock can't reach the server.
> (System Settings → Network → Firewall.)

## 3. Point the dock at it

On the dock's settings page (`http://<DOCK-IP>/apps` → **Claude Usage**), set
**“Claude Code helper URL”** to the **On LAN** URL above (e.g. `http://192.168.1.50:8787/usage`).

---

## 4. Keep it running automatically (recommended)

So the Claude Code panel works without leaving a terminal open, install it as a
background service: **double-click `Install Background Service.command`** (in this
folder). It auto-starts at login and restarts if it crashes.

> **Why it copies the server to `~/.claude-dock/`:** macOS privacy protection (TCC)
> blocks background (launchd) services from reading `~/Documents`. A service whose
> script lives under `~/Documents` fails with `Operation not permitted`. The installer
> therefore copies `claude_dock_server.py` to `~/.claude-dock/` (an unprotected
> location) and points the LaunchAgent there. Re-run the installer after you change
> `claude_dock_server.py` so the copy stays up to date.

To remove it: double-click `Uninstall Background Service.command`.

Logs: `~/.claude-dock/companion.out.log` and `~/.claude-dock/companion.err.log`.

---

## Notes

- The **Mac must be on and running the server** for the Claude Code panel to update.
  (The API panel on the dock works independently and needs no Mac.)
- “Tokens” here = input (incl. cached/cache-read) + output, summed per **local** day.
  Claude Code re-reads a lot of cached context, so the input number is large — that's
  expected; `Out` is the newly generated text.
- Endpoint: `GET /usage?days=30` → JSON `{ok, days:[{date,label,input,output,total}], today, totals}`.
