# -*- coding: utf-8 -*-
# Claude Usage - data service for the Vobot Mini Dock
#
# Fetches Claude token usage via the Anthropic "Usage & Cost Admin API":
#   GET https://api.anthropic.com/v1/organizations/usage_report/messages
# Docs: https://platform.claude.com/docs/en/api/usage-cost-api
#
# IMPORTANT: this API requires an *Admin* API key (starts with "sk-ant-admin...")
# and is only available to organizations, not to individual accounts.
#
# We use the asynchronous HTTP module "arequests" (like the official Stock View
# app) so the UI does not freeze during the network request. If an older
# firmware does not ship "arequests", fall back to synchronous "urequests"
# (see README).

import arequests as request

_API_HOST = "https://api.anthropic.com"
_USAGE_PATH = "/v1/organizations/usage_report/messages"
_ANTHROPIC_VERSION = "2023-06-01"

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# ---------------------------------------------------------------------------
# Calendar math (pure integer, independent of the MicroPython epoch)
#
# We build the RFC-3339 timestamps for the API ourselves instead of relying on
# time.gmtime() (whose epoch is 1970 or 2000 depending on the port).
# Basis: "days_from_civil" / "civil_from_days" (Howard Hinnant), returning a
# day number relative to 1970-01-01.
# ---------------------------------------------------------------------------

def days_from_civil(y, m, d):
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return (y + (1 if m <= 2 else 0), m, d)


def _utc_today_daynum():
    """Current UTC day number (days since 1970-01-01) from the device clock."""
    import clocktime
    dt = clocktime.datetime()          # local time: (Y, M, D, hh, mm, ss, wday, yday)
    tz = clocktime.tzoffset()          # seconds east of UTC
    local_secs = days_from_civil(dt[0], dt[1], dt[2]) * 86400 + dt[3] * 3600 + dt[4] * 60 + dt[5]
    utc_secs = local_secs - tz
    return utc_secs // 86400            # floor division -> correct UTC day number


def _fmt_date(daynum, hh=0, mm=0, ss=0):
    y, mo, d = civil_from_days(daynum)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (y, mo, d, hh, mm, ss)


def day_label(daynum):
    """Short axis label, e.g. '02 Jun'."""
    y, mo, d = civil_from_days(daynum)
    return "%02d %s" % (d, _MONTHS[mo - 1])


def _daynum_from_iso(s):
    # s e.g. "2025-08-01T00:00:00Z"
    try:
        return days_from_civil(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Token aggregation
# ---------------------------------------------------------------------------

def _sum_result(r):
    """Return (input_tokens, output_tokens) for one result entry."""
    cc = r.get("cache_creation") or {}
    inp = ((r.get("uncached_input_tokens") or 0)
           + (r.get("cache_read_input_tokens") or 0)
           + (cc.get("ephemeral_5m_input_tokens") or 0)
           + (cc.get("ephemeral_1h_input_tokens") or 0))
    out = r.get("output_tokens") or 0
    return inp, out


def _parse(data, start_day, days):
    """Turn the API response into a per-day list, zero-filled for missing days."""
    by_day = {}
    for bucket in data.get("data", []):
        dn = _daynum_from_iso(bucket.get("starting_at", ""))
        if dn is None:
            continue
        ti = to = 0
        for r in bucket.get("results", []):
            i, o = _sum_result(r)
            ti += i
            to += o
        prev = by_day.get(dn, (0, 0))
        by_day[dn] = (prev[0] + ti, prev[1] + to)

    out = []
    for k in range(days):
        dn = start_day + k
        inp, o = by_day.get(dn, (0, 0))
        out.append({"day": dn, "label": day_label(dn),
                    "input": inp, "output": o, "total": inp + o})
    return out


async def fetch_usage(api_key, days=7):
    """
    Fetch the daily token usage for the last `days` days.

    Returns (dict):
      {"ok": True,  "days": [ {day, input, output, total}, ... ]}
      {"ok": False, "status": <int>, "error": "<text>"}
    """
    if not api_key:
        return {"ok": False, "status": 0, "error": "No API key configured"}

    today = _utc_today_daynum()
    start = today - (days - 1)
    starting_at = _fmt_date(start)
    ending_at = _fmt_date(today + 1)   # exclusive end -> today's bucket fully included

    url = "%s%s?starting_at=%s&ending_at=%s&bucket_width=1d&limit=%d" % (
        _API_HOST, _USAGE_PATH, starting_at, ending_at, days)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
    }

    resp = None
    try:
        resp = await request.request("GET", url, headers=headers)
        status = resp.status_code
        if status == 200:
            data = await resp.json()
            return {"ok": True, "status": 200, "days": _parse(data, start, days)}

        # Error response -> read message from the body if present
        msg = ""
        try:
            body = await resp.json()
            msg = (body.get("error") or {}).get("message", "")
        except Exception:
            pass
        return {"ok": False, "status": status, "error": msg or _status_hint(status)}
    except Exception as e:
        return {"ok": False, "status": -1, "error": "Network error: %s" % str(e)}
    finally:
        # Close the socket cleanly (if the implementation offers close())
        try:
            if resp is not None and hasattr(resp, "close"):
                resp.close()
        except Exception:
            pass


def _status_hint(status):
    if status == 401:
        return "Invalid Admin key (401)"
    if status == 403:
        return "Access denied (403) - Admin key/org required"
    if status == 429:
        return "Too many requests (429)"
    return "HTTP error %d" % status


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def fmt_tokens(n):
    """Compact display of large numbers: 1.23M, 345.6K, 42."""
    n = int(n)
    if n >= 1000000000:
        return "%.2fB" % (n / 1000000000.0)
    if n >= 1000000:
        return "%.2fM" % (n / 1000000.0)
    if n >= 1000:
        return "%.1fK" % (n / 1000.0)
    return str(n)
