# Claude Dock – cloud hub (multiple computers, different networks)

Use this when you run Claude Code on **several machines on different networks** and the
dock can't reach any of them directly.

```
  Mac (home)  ─┐
  Laptop (work)─┤── push daily totals ──>  HUB (always-on, public HTTPS)  <── GET ── Vobot dock
  PC (...)     ─┘     claude_dock_push.py        claude_dock_hub.py
```

- Each machine **pushes** its local-log totals to one hub (no inbound access to the machines needed).
- The hub **merges all machines** and serves one JSON URL.
- The dock reads only the hub → you see combined usage from everywhere.
- Standard library only; the hub stores **token counts only**, protected by a shared token.

> There is **no official Anthropic API** for subscription/plan usage (only the metered API
> has one). Claude Code's own 5h/weekly numbers come from an internal OAuth endpoint that is
> for Anthropic's apps only — using it for your own tools risks your account. So local logs +
> this hub is the safe, supported approach.

---

## 1. Pick a host for the hub

You need one always-on host with a **public HTTPS URL** the dock can reach:

- **Option A – tiny VPS (simplest):** any $4–6/mo Linux VPS + a domain. HTTPS via Caddy.
- **Option B – no VPS:** an always-on box at home (Raspberry Pi, Mac mini, NAS) exposed with a
  **Cloudflare Tunnel** or **Tailscale Funnel** (both give a public HTTPS URL without opening
  ports). Run the hub locally on `:8899` and point the tunnel at it.

Pick a long random **shared secret** (the "token"), e.g. `openssl rand -hex 24`. The same value
goes on the hub, every pusher, and in the dock URL.

## 2. Deploy the hub

**VPS (Linux):**
```bash
sudo mkdir -p /opt/claude-dock && sudo cp claude_dock_hub.py /opt/claude-dock/
# edit the token in the service file, then:
sudo cp claude-dock-hub.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now claude-dock-hub
curl -s localhost:8899/            # -> "Claude Dock hub OK"
```
Put HTTPS in front with Caddy (see `Caddyfile.example`) so the public URL is
`https://hub.example.com`. (Tunnel users: skip Caddy; the tunnel provides HTTPS.)

**Quick manual run (any OS), for testing:**
```bash
CLAUDE_DOCK_TOKEN=yourtoken python3 claude_dock_hub.py
```

## 3. Run a pusher on EACH Claude Code machine

Copy just `claude_dock_push.py` to each machine. Test first:
```bash
python3 claude_dock_push.py --print          # shows what it would send (numbers only)
```
Send once:
```bash
CLAUDE_DOCK_HUB=https://hub.example.com/push \
CLAUDE_DOCK_TOKEN=yourtoken \
CLAUDE_DOCK_MACHINE=my-macbook \
python3 claude_dock_push.py                   # -> "pushed my-macbook: {...ok...}"
```

Make it run every ~10 minutes:
- **macOS:** edit the env values + paths in `com.vobot.claude-push.plist`, then
  ```bash
  cp com.vobot.claude-push.plist ~/Library/LaunchAgents/
  launchctl load ~/Library/LaunchAgents/com.vobot.claude-push.plist
  ```
- **Linux:** add a cron line:
  ```bash
  */10 * * * * CLAUDE_DOCK_HUB=https://hub.example.com/push CLAUDE_DOCK_TOKEN=yourtoken CLAUDE_DOCK_MACHINE=$(hostname) /usr/bin/python3 /path/to/claude_dock_push.py
  ```

Give each machine a distinct `CLAUDE_DOCK_MACHINE` name (pushes are stored per machine and summed).

## 4. Point the dock at the hub

In the dock app settings (`http://<DOCK-IP>/apps` → **Claude Usage**), set
**“Claude Code helper URL”** to:
```
https://hub.example.com/usage?token=yourtoken
```
That's it — the dock app itself doesn't change. The Claude Code panel now shows the sum of all
machines that push.

---

## Verify
```bash
curl -s "https://hub.example.com/usage?days=7&token=yourtoken" | python3 -m json.tool
```
You should see merged `days`, `today`, `totals`, and a `machines` list.

## Security notes
- The token is the only gate — keep it long and private. Data is just token counts, but don't run the hub **open** (no token).
- Always use **HTTPS** (Caddy or a tunnel) so the token isn't sent in clear text.
- The hub never sees your prompts/code — pushers send only per-day input/output token counts.

## Files
| File | Where it runs |
|---|---|
| `claude_dock_hub.py` | the hub host (VPS / always-on box) |
| `claude_dock_push.py` | every Claude Code machine |
| `claude-dock-hub.service` | systemd unit for the hub (Linux) |
| `com.vobot.claude-push.plist` | launchd job for the pusher (macOS) |
| `Caddyfile.example` | HTTPS reverse proxy for the hub |
