#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Dock PUSHER - run this on EVERY computer where you use Claude Code / Cowork.

Reads this machine's local transcript logs (~/.claude/projects/**/*.jsonl),
sums tokens per local day, and POSTs the totals to your central hub
(claude_dock_hub.py). Run it periodically (cron / launchd) so the dock stays current.

This is the multi-machine / multi-network answer: each machine pushes to one hub;
the dock reads only the hub. Self-contained (standard library only) — copy just
this one file onto each machine.

Config via environment:
  CLAUDE_DOCK_HUB     hub push URL, e.g. https://my-hub.example.com/push   (REQUIRED)
  CLAUDE_DOCK_TOKEN   shared secret, same value as on the hub               (REQUIRED)
  CLAUDE_DOCK_MACHINE label for this machine (default: hostname)
  CLAUDE_DOCK_DAYS    how many days to send (default 31)

Usage:
  CLAUDE_DOCK_HUB=https://hub/push CLAUDE_DOCK_TOKEN=secret python3 claude_dock_push.py
  python3 claude_dock_push.py --print     # show what would be sent, don't send
"""

import os
import sys
import glob
import json
import socket
import urllib.request
from datetime import datetime, timezone

CLAUDE_PROJECTS = os.path.join(os.path.expanduser("~"), ".claude", "projects")


def _local_date(ts):
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone()
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


def _aggregate():
    """Return {date: [input, output]} across all local Claude Code logs."""
    daily = {}
    for path in glob.glob(os.path.join(CLAUDE_PROJECTS, "**", "*.jsonl"), recursive=True):
        try:
            fh = open(path, "rb")
        except OSError:
            continue
        with fh:
            for raw in fh:
                if b'"assistant"' not in raw:
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
                    date = _local_date(ts)
                except Exception:
                    continue
                inp = ((u.get("input_tokens") or 0)
                       + (u.get("cache_read_input_tokens") or 0)
                       + (u.get("cache_creation_input_tokens") or 0))
                out = u.get("output_tokens") or 0
                slot = daily.get(date)
                if slot is None:
                    daily[date] = [inp, out]
                else:
                    slot[0] += inp
                    slot[1] += out
    return daily


def build_snapshot(days):
    daily = _aggregate()
    today_ord = datetime.now().astimezone().toordinal()
    out = []
    for k in range(days):
        d = datetime.fromordinal(today_ord - (days - 1) + k)
        date = "%04d-%02d-%02d" % (d.year, d.month, d.day)
        io = daily.get(date, [0, 0])
        out.append({"date": date, "input": io[0], "output": io[1]})
    machine = os.environ.get("CLAUDE_DOCK_MACHINE") or socket.gethostname()
    return {"machine": machine, "days": out}


def main(argv):
    days = int(os.environ.get("CLAUDE_DOCK_DAYS", "31"))
    snap = build_snapshot(days)

    if "--print" in argv:
        print(json.dumps(snap, indent=2))
        return

    hub = os.environ.get("CLAUDE_DOCK_HUB", "")
    token = os.environ.get("CLAUDE_DOCK_TOKEN", "")
    if not hub or not token:
        sys.exit("Set CLAUDE_DOCK_HUB and CLAUDE_DOCK_TOKEN (or use --print).")

    snap["token"] = token
    data = json.dumps(snap).encode("utf-8")
    req = urllib.request.Request(hub, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "X-Auth-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print("pushed %s: %s" % (snap["machine"], resp.read().decode("utf-8")))
    except Exception as e:
        sys.exit("push failed: %s" % e)


if __name__ == "__main__":
    main(sys.argv[1:])
