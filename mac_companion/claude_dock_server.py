#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Dock - local companion server for the Vobot Mini Dock.

Reads Claude Code / Cowork transcript logs under ~/.claude/projects/**/*.jsonl,
aggregates token usage per (local) day, and serves it as JSON so the Vobot Mini
Dock app can display your subscription / Claude Code usage on the device.

Why a local helper:
  Claude Code / Cowork usage runs through your subscription plan, NOT the metered
  API, so it does not appear in the Anthropic Usage & Cost Admin API. The token
  counts are, however, written to local transcript logs. This server turns those
  logs into a tiny JSON feed on your LAN.

Usage:
  python3 claude_dock_server.py                # start server on 0.0.0.0:8787
  python3 claude_dock_server.py --port 9000    # custom port
  python3 claude_dock_server.py --print 14     # print 14-day payload and exit (self-test)

Endpoints:
  GET /usage?days=30   -> JSON {ok, source, generated_at, tz, days:[...], today, totals}
  GET /                -> short health/status text

Only the Python standard library is used (no pip installs).
"""

import os
import sys
import glob
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Where Claude Code / Cowork write their transcripts.
CLAUDE_PROJECTS = os.path.join(os.path.expanduser("~"), ".claude", "projects")

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

DEFAULT_PORT = 8787
MAX_DAYS = 31
RESCAN_MIN_INTERVAL = 4.0   # seconds; avoid re-reading logs on every rapid request

# ---------------------------------------------------------------------------
# Incremental log scanning
#
# Logs are append-only JSONL. We remember, per file, the byte offset we have
# already processed plus that file's per-day token totals. On each scan we read
# only the newly appended, complete lines. A shrunk file (rotation/rewrite) is
# re-read from the start.
# ---------------------------------------------------------------------------

_state = {}            # path -> {"off": int, "size": int, "mtime": float, "daily": {date: [in, out, label]}}
_state_lock = threading.Lock()
_last_scan_monotonic = [None]   # None = never scanned yet (force first scan)


def _local_date_label(ts):
    """ISO-8601 UTC timestamp (…Z) -> (local 'YYYY-MM-DD', 'DD Mon')."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone()   # convert to the Mac's local time zone
    return ("%04d-%02d-%02d" % (dt.year, dt.month, dt.day),
            "%02d %s" % (dt.day, MONTHS[dt.month - 1]))


def _tokens_from_usage(u):
    inp = ((u.get("input_tokens") or 0)
           + (u.get("cache_read_input_tokens") or 0)
           + (u.get("cache_creation_input_tokens") or 0))
    out = u.get("output_tokens") or 0
    return inp, out


def _scan_file(path, rec):
    """Incrementally fold a single JSONL file into its per-day token record."""
    try:
        st = os.stat(path)
    except OSError:
        return rec

    if rec is not None and st.st_size < rec["off"]:
        rec = None                       # file shrank -> rotated/rewritten, re-read
    if rec is None:
        rec = {"off": 0, "size": 0, "mtime": 0.0, "daily": {}}
    if rec["size"] == st.st_size and rec["mtime"] == st.st_mtime:
        return rec                       # unchanged since last scan

    try:
        with open(path, "rb") as fh:
            fh.seek(rec["off"])
            data = fh.read()
    except OSError:
        return rec

    last_nl = data.rfind(b"\n")
    if last_nl == -1:
        # only a partial line so far; remember size/mtime, keep offset
        rec["size"] = st.st_size
        rec["mtime"] = st.st_mtime
        return rec

    for raw in data[:last_nl].split(b"\n"):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if obj.get("type") != "assistant":
            continue
        msg = obj.get("message") or {}
        u = msg.get("usage")
        ts = obj.get("timestamp")
        if not u or not ts:
            continue
        try:
            date, label = _local_date_label(ts)
        except Exception:
            continue
        inp, out = _tokens_from_usage(u)
        slot = rec["daily"].get(date)
        if slot is None:
            rec["daily"][date] = [inp, out, label]
        else:
            slot[0] += inp
            slot[1] += out

    rec["off"] += last_nl + 1
    rec["size"] = st.st_size
    rec["mtime"] = st.st_mtime
    return rec


def _merge_daily():
    """Merge every file's per-day record into one {date: [in, out, label]}."""
    merged = {}
    for rec in _state.values():
        for date, (i, o, label) in rec["daily"].items():
            m = merged.get(date)
            if m is None:
                merged[date] = [i, o, label]
            else:
                m[0] += i
                m[1] += o
    return merged


def scan(force=False):
    """Update internal state from disk and return merged per-day totals."""
    import time
    with _state_lock:
        now = time.monotonic()
        if (not force and _last_scan_monotonic[0] is not None
                and (now - _last_scan_monotonic[0]) < RESCAN_MIN_INTERVAL):
            return _merge_daily()
        files = glob.glob(os.path.join(CLAUDE_PROJECTS, "**", "*.jsonl"), recursive=True)
        for f in files:
            _state[f] = _scan_file(f, _state.get(f))
        _last_scan_monotonic[0] = now
        return _merge_daily()


def _today_local_daynum():
    n = datetime.now().astimezone()
    return (datetime(n.year, n.month, n.day).toordinal())


def build_payload(days=7):
    days = max(1, min(int(days), MAX_DAYS))
    merged = scan()

    today_ord = _today_local_daynum()
    out_days = []
    for k in range(days):
        d = datetime.fromordinal(today_ord - (days - 1) + k)
        date = "%04d-%02d-%02d" % (d.year, d.month, d.day)
        label = "%02d %s" % (d.day, MONTHS[d.month - 1])
        i, o, _lbl = merged.get(date, [0, 0, label])
        out_days.append({"date": date, "label": label,
                         "input": i, "output": o, "total": i + o})

    period_total = sum(x["total"] for x in out_days)
    today = out_days[-1]
    gen = datetime.now().astimezone()
    return {
        "ok": True,
        "source": "claude_code_local",
        "generated_at": gen.isoformat(),
        "tz": gen.tzname() or "",
        "days": out_days,
        "today": today,
        "totals": {"period_total": period_total, "period_days": days,
                   "avg_per_day": period_total // days},
    }


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = self.path.split("?", 1)
        route = path[0]
        days = 7
        if len(path) > 1:
            for kv in path[1].split("&"):
                if kv.startswith("days="):
                    try:
                        days = int(kv[5:])
                    except ValueError:
                        pass

        if route in ("/usage", "/usage/"):
            try:
                self._send(200, json.dumps(build_payload(days)))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}))
        elif route in ("/", "/health"):
            try:
                p = build_payload(7)
                msg = ("Claude Dock companion OK\n"
                       "today=%d tokens  7d=%d tokens\n"
                       "GET /usage?days=30 for JSON\n"
                       % (p["today"]["total"], p["totals"]["period_total"]))
            except Exception as e:
                msg = "Claude Dock companion running, but scan failed: %s\n" % e
            self._send(200, msg, "text/plain; charset=utf-8")
        else:
            self._send(404, json.dumps({"ok": False, "error": "not found"}))

    def log_message(self, *args):
        pass   # keep the console quiet


def _lan_ip():
    """Best-effort LAN IP for the startup hint (no traffic is actually sent)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def serve(port):
    if not os.path.isdir(CLAUDE_PROJECTS):
        print("WARNING: %s not found. Is Claude Code installed/used on this Mac?"
              % CLAUDE_PROJECTS)
    # Bind the port immediately; the first /usage request does the (possibly slow)
    # initial log scan. This keeps startup instant even with large logs.
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    ip = _lan_ip()
    print("Claude Dock companion running.")
    print("  Local:   http://127.0.0.1:%d/usage" % port)
    print("  On LAN:  http://%s:%d/usage" % (ip, port))
    print("Enter this URL (the LAN one) in the Vobot app settings as 'Claude Code helper URL'.")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        httpd.shutdown()


def main(argv):
    port = DEFAULT_PORT
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    if "--print" in argv:
        n = 7
        i = argv.index("--print")
        if i + 1 < len(argv) and argv[i + 1].isdigit():
            n = int(argv[i + 1])
        print(json.dumps(build_payload(n), indent=2))
        return
    serve(port)


if __name__ == "__main__":
    main(sys.argv[1:])
