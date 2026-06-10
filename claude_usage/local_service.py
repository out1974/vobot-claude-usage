# -*- coding: utf-8 -*-
# Claude Usage - client for the local Mac companion (subscription / Claude Code usage)
#
# Talks to claude_dock_server.py running on your Mac (see ../mac_companion/),
# which reads the local Claude Code / Cowork transcript logs and serves daily
# token totals as JSON. This is how the dock shows usage that runs through your
# subscription plan instead of the metered API.

import arequests as request


async def fetch_usage(helper_url, days=7):
    """
    GET <helper_url>?days=N from the Mac companion.

    Returns:
      {"ok": True,  "days": [ {date, label, input, output, total}, ... ]}
      {"ok": False, "status": <int>, "error": "<text>"}
    """
    if not helper_url:
        return {"ok": False, "status": 0, "error": "Set helper URL"}

    sep = "&" if "?" in helper_url else "?"
    url = "%s%sdays=%d" % (helper_url, sep, days)

    resp = None
    try:
        resp = await request.request("GET", url)
        if resp.status_code == 200:
            data = await resp.json()
            return {"ok": True, "status": 200, "days": data.get("days", [])}
        return {"ok": False, "status": resp.status_code,
                "error": "Helper HTTP %d" % resp.status_code}
    except Exception:
        return {"ok": False, "status": -1, "error": "Helper offline"}
    finally:
        try:
            if resp is not None and hasattr(resp, "close"):
                resp.close()
        except Exception:
            pass
