# Claude Usage – Claude token usage on the Vobot Mini Dock

A Vobot Mini Dock app that shows your Claude token usage in **two panels**:

- **Top – Claude Code** (subscription): usage from Claude Code / Cowork, read from a
  small companion server on your Mac (it parses the local transcript logs).
- **Bottom – API** (pay-as-you-go): metered API usage from the Anthropic
  Usage & Cost Admin API.

Each panel shows **today's tokens**, **In/Out**, a **7/14/30-day total + average**, and a
**daily bar chart**.

> **Why two sources?** Subscription usage (Claude Code / Cowork / claude.ai) runs through
> your plan and is **not** in the metered API — so it can only come from local logs.
> Metered API usage comes from the Admin API. They are genuinely separate numbers.

---

## Files

```
claude_usage/            <- copy THIS folder to the dock's /apps
├── __init__.py          UI (two panels), lifecycle, settings form
├── service.py           API usage (Anthropic Usage & Cost Admin API)
├── local_service.py     Claude Code usage (talks to the Mac companion)
└── manifest.yml
```

The Mac companion lives in **`../mac_companion/`** (see its README).

---

## Setup

### 1. Install the app on the dock
1. Enable **Developer Mode** on the dock, connect via **USB-C**.
2. In **Thonny** → *View → Files*, open the device's **`apps`** folder.
3. Right-click the local **`claude_usage`** folder → **Upload to /apps**
   (make sure `local_service.py` is included).
4. Press **Ctrl+D** in the Thonny shell to reboot. “Claude Usage” appears in the menu.

### 2. Claude Code panel (subscription)
Choose the source that matches your setup, then put its URL into
**“Claude Code helper URL”** in the dock settings (`http://<DOCK-IP>/apps` → **Claude Usage**):

- **One machine, same Wi-Fi as the dock** → run the LAN companion
  ([`../mac_companion/README.md`](../mac_companion/README.md)):
  ```bash
  python3 "../mac_companion/claude_dock_server.py"
  ```
  Use the printed **On LAN** URL, e.g. `http://192.168.1.50:8787/usage`.

- **Multiple machines / different networks** → use the cloud hub
  ([`../cloud_hub/README.md`](../cloud_hub/README.md)). Each machine pushes to the hub; the dock
  reads `https://hub.example.com/usage?token=yourtoken`.

### 3. API panel (optional)
Paste an **Admin API key** (`sk-ant-admin…`, organizations only) into **“Anthropic Admin API key”**.
Leave empty to hide the API panel. (Create one: Console → Settings → Admin keys.)

### 4. Time range
Choose **7 / 14 / 30 days** for both panels.

---

## Settings reference

| Field | Purpose |
|---|---|
| **Claude Code helper URL** | URL of the Mac companion, e.g. `http://192.168.1.50:8787/usage`. Empty → Claude Code panel shows “Set helper URL”. |
| **Anthropic Admin API key** | `sk-ant-admin…` for metered API usage. Empty → API panel shows “Set helper URL”/no key. |
| **Time range** | 7 / 14 / 30 days. |

---

## Troubleshooting

| Panel shows | Cause / fix |
|---|---|
| **Set helper URL** (Code panel) | Enter the Mac companion URL in settings. |
| **Helper offline** (Code panel) | Mac companion not running, wrong URL/IP, Mac asleep, or macOS firewall blocking `python3` (allow incoming connections). |
| **No usage** (a panel) | No usage in the selected range for that source (expected if you don't use that channel). |
| **Access denied (401/403)** (API panel) | Wrong key, or not an Admin key, or individual (non-org) account. |
| **No network** (whole screen) | Wait until the dock's Wi-Fi is connected. |

### `arequests` vs `urequests`
Both `service.py` and `local_service.py` use async `arequests` (non-blocking). On older
firmware without `arequests`, swap to a `urequests` shim — see the snippet in the project
root README / git history.

---

## Notes
- The dock refreshes every ~10 minutes (and when you open the app).
- The Claude Code panel needs the Mac on + companion running. The API panel is independent.
- Sources: [Vobot dev docs](https://dock.myvobot.com/developer/) · [example apps](https://github.com/myvobot/dock-mini-apps) · [Anthropic Usage & Cost API](https://platform.claude.com/docs/en/api/usage-cost-api).
