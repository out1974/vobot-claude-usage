#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Dock HUB - central aggregator for multi-machine Claude Code usage.

Runs on one always-reachable host (a small VPS, or behind a tunnel). Each of
your Claude Code machines runs claude_dock_push.py, which reads its local logs
and POSTs daily token totals here. The Vobot dock then reads ONE URL (this hub),
so usage from all machines/networks is combined.

Endpoints:
  POST /push        body: {"machine": "...", "days": [{"date","input","output"}, ...]}
                    auth: token in body ("token") or header "X-Auth-Token"
  GET  /usage?days=N&token=...   -> dock JSON {ok, days:[{date,label,input,output,total}], today, totals}
  GET  /            -> health text (no token)

Config via environment:
  CLAUDE_DOCK_TOKEN   shared secret (REQUIRED). Same value on hub, pushers, and the dock URL.
  PORT                listen port (default 8899)
  CLAUDE_DOCK_STATE   state file path (default ~/.claude_dock_hub.json)

Standard library only.
"""

import os
import sys
import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

TOKEN = os.environ.get("CLAUDE_DOCK_TOKEN", "")
PORT = int(os.environ.get("PORT", "8899"))
STATE_PATH = os.environ.get("CLAUDE_DOCK_STATE",
                            os.path.join(os.path.expanduser("~"), ".claude_dock_hub.json"))
MAX_DAYS = 60

_lock = threading.Lock()


def load_state():
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {"machines": {}}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE_PATH)


def apply_push(state, body):
    """Replace one machine's snapshot (idempotent — repeated pushes don't double count)."""
    machine = str(body.get("machine") or "unknown")[:64]
    days = body.get("days") or []
    daymap = {}
    for d in days:
        date = d.get("date")
        if not date:
            continue
        daymap[date] = [int(d.get("input") or 0), int(d.get("output") or 0)]
    state.setdefault("machines", {})[machine] = {
        "updated": datetime.now().astimezone().isoformat(),
        "days": daymap,
    }
    return machine


def _merge(state):
    """Sum all machines' per-day totals -> {date: [in, out]}."""
    merged = {}
    for rec in state.get("machines", {}).values():
        for date, io in rec.get("days", {}).items():
            m = merged.get(date)
            if m is None:
                merged[date] = [io[0], io[1]]
            else:
                m[0] += io[0]
                m[1] += io[1]
    return merged


def build_usage(state, days):
    days = max(1, min(int(days), MAX_DAYS))
    merged = _merge(state)

    today_ord = datetime.now().astimezone().toordinal()
    # make sure the freshest pushed day is visible even across time zones
    seen_max = today_ord
    for date in merged:
        try:
            y, m, d = (int(x) for x in date.split("-"))
            seen_max = max(seen_max, datetime(y, m, d).toordinal())
        except Exception:
            pass
    end_ord = max(today_ord, seen_max)

    out = []
    for k in range(days):
        d = datetime.fromordinal(end_ord - (days - 1) + k)
        date = "%04d-%02d-%02d" % (d.year, d.month, d.day)
        label = "%02d %s" % (d.day, MONTHS[d.month - 1])
        io = merged.get(date, [0, 0])
        out.append({"date": date, "label": label,
                    "input": io[0], "output": io[1], "total": io[0] + io[1]})

    period_total = sum(x["total"] for x in out)
    return {
        "ok": True,
        "source": "claude_code_hub",
        "generated_at": datetime.now().astimezone().isoformat(),
        "machines": list(state.get("machines", {}).keys()),
        "days": out,
        "today": out[-1],
        "totals": {"period_total": period_total, "period_days": days,
                   "avg_per_day": period_total // days},
    }


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

    def _auth_ok(self, query_token, header_token, body_token):
        if not TOKEN:
            return True   # no token configured -> open (not recommended)
        return TOKEN in (query_token, header_token, body_token)

    def do_GET(self):
        parts = self.path.split("?", 1)
        route = parts[0]
        q = {}
        if len(parts) > 1:
            for kv in parts[1].split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    q[k] = v

        if route in ("/", "/health"):
            self._send(200, "Claude Dock hub OK\n", "text/plain; charset=utf-8")
            return

        if route in ("/usage", "/usage/"):
            if not self._auth_ok(q.get("token"), self.headers.get("X-Auth-Token"), None):
                self._send(401, json.dumps({"ok": False, "error": "bad token"}))
                return
            try:
                days = int(q.get("days", "7"))
            except ValueError:
                days = 7
            with _lock:
                state = load_state()
                self._send(200, json.dumps(build_usage(state, days)))
            return

        self._send(404, json.dumps({"ok": False, "error": "not found"}))

    def do_POST(self):
        if self.path.split("?", 1)[0] not in ("/push", "/push/"):
            self._send(404, json.dumps({"ok": False, "error": "not found"}))
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._send(400, json.dumps({"ok": False, "error": "bad json"}))
            return
        if not self._auth_ok(None, self.headers.get("X-Auth-Token"), body.get("token")):
            self._send(401, json.dumps({"ok": False, "error": "bad token"}))
            return
        with _lock:
            state = load_state()
            machine = apply_push(state, body)
            save_state(state)
        self._send(200, json.dumps({"ok": True, "machine": machine}))

    def log_message(self, *args):
        pass


def main(argv):
    if "--selftest" in argv:
        st = {"machines": {}}
        apply_push(st, {"machine": "a", "days": [{"date": "2026-06-10", "input": 100, "output": 10}]})
        apply_push(st, {"machine": "b", "days": [{"date": "2026-06-10", "input": 5, "output": 1}]})
        apply_push(st, {"machine": "a", "days": [{"date": "2026-06-10", "input": 100, "output": 10}]})  # repeat
        u = build_usage(st, 3)
        print("merged today (expect in=105 out=11):", u["today"]["input"], u["today"]["output"])
        return
    if not TOKEN:
        print("WARNING: CLAUDE_DOCK_TOKEN is not set -> the hub is OPEN. Set a shared secret!")
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("Claude Dock hub listening on :%d  (state: %s)" % (PORT, STATE_PATH))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main(sys.argv[1:])
