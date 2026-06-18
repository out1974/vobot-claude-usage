# -*- coding: utf-8 -*-
# Claude Usage - Claude token usage on the Vobot Mini Dock
#
# Adaptive layout:
#   - Only the Claude Code helper URL set  -> full-screen Claude Code dashboard.
#   - Only the Admin API key set           -> full-screen API dashboard.
#   - Both set                             -> two stacked panels (Code + API).
#
# Claude Code usage comes from a companion on your Mac / a cloud hub (local logs).
# API usage comes from the Anthropic Usage & Cost Admin API.

import net
import asyncio
import clocktime
import lvgl as lv
import peripherals
from micropython import const

from . import service          # API usage (Anthropic Admin API)
from . import local_service    # Claude Code usage (Mac companion / cloud hub)

NAME = "Claude Usage"
CAN_BE_AUTO_SWITCHED = True
# Resource paths use NAME (the platform renames the app folder to NAME on install).
# Literal string (not an f-string) so the launcher can read the icon path statically.
ICON = "A:apps/Claude Usage/resources/icon.png"

_SCR_WIDTH, _SCR_HEIGHT = peripherals.screen.screen_resolution
_UPDATE_INTERVAL = const(600)   # refresh every 10 minutes

# Colors
_C_BG = lv.color_hex(0x000000)
_C_CODE = lv.color_hex(0xFF8A3D)    # Claude Code accent (orange)
_C_API = lv.color_hex(0x0BB4ED)     # API accent (blue)
_C_WHITE = lv.color_hex(0xFFFFFF)
_C_GREY = lv.color_hex(0x9AA0A6)
_C_DIV = lv.color_hex(0x333333)

# State
_scr = None
_app_mgr = None
_last_updated = 0
_code = None
_api = None


# ---------------------------------------------------------------------------
# Settings (web form)
# ---------------------------------------------------------------------------

def get_settings_json():
    return {
        "category": "Tools",
        "form": [
            {
                "type": "input",
                "default": "",
                "caption": "Claude Code helper URL",
                "name": "helper_url",
                "attributes": {"maxLength": 160, "placeholder": "http://192.168.x.x:8787/usage"},
                "tip": ("URL of the Mac companion or cloud hub that reports your "
                        "Claude Code / Cowork usage. Leave empty to hide the Claude Code panel."),
            },
            {
                "type": "input",
                "default": "",
                "caption": "Anthropic Admin API key (optional)",
                "name": "api_key",
                "attributes": {"maxLength": 200, "placeholder": "sk-ant-admin... (leave empty for subscription only)"},
                "tip": ("Only for metered API usage (organizations). Subscription / Claude "
                        "Code usage does NOT appear here - leave empty if you only use a plan."),
                "hint": {
                    "url": "https://console.anthropic.com/settings/admin-keys",
                    "label": "Create an Admin key in the Anthropic Console",
                },
            },
            {
                "type": "select",
                "default": "7",
                "caption": "Time range",
                "name": "days",
                "options": [("7 days", "7"), ("14 days", "14"), ("30 days", "30")],
                "tip": "Number of days shown.",
            },
        ],
    }


def _cfg():
    return _app_mgr.config() if _app_mgr else {}


def _get_days():
    try:
        d = int(_cfg().get("days", "7"))
        return d if d in (7, 14, 30) else 7
    except Exception:
        return 7


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _clear():
    if _scr:
        _scr.clean()


def _label(text, font, color, align, x, y, parent=None):
    lb = lv.label(parent or _scr)
    lb.set_text(text)
    lb.set_style_text_font(font, 0)
    lb.set_style_text_color(color, 0)
    lb.align(align, x, y)
    return lb


def _show_message(title, msg):
    if not _scr:
        return
    _clear()
    t = _label(title, lv.font_ascii_bold_22, _C_WHITE, lv.ALIGN.CENTER, 0, -16)
    t.set_width(_SCR_WIDTH - 24)
    t.set_long_mode(lv.label.LONG.WRAP)
    t.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
    m = _label(msg, lv.font_ascii_18, _C_GREY, lv.ALIGN.CENTER, 0, 28)
    m.set_width(_SCR_WIDTH - 24)
    m.set_long_mode(lv.label.LONG.WRAP)
    m.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)


def _divider(y):
    line = lv.line(_scr)
    line.set_points([{"x": 0, "y": 0}, {"x": _SCR_WIDTH, "y": 0}], 2)
    line.align(lv.ALIGN.TOP_LEFT, 0, y)
    line.set_style_line_width(1, 0)
    line.set_style_line_color(_C_DIV, 0)


def _chart(data, color, w, h, align, x, y):
    chart = lv.chart(_scr)
    chart.set_size(w, h)
    chart.align(align, x, y)
    chart.set_type(lv.chart.TYPE.BAR)
    chart.set_point_count(len(data))
    chart.set_div_line_count(3, 0)
    chart.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    chart.set_style_radius(0, lv.PART.MAIN)
    chart.set_style_border_width(0, lv.PART.MAIN)
    chart.set_style_line_color(_C_DIV, lv.PART.MAIN)
    chart.set_style_size(0, 0, lv.PART.INDICATOR)
    mx = 1
    for d in data:
        if d["total"] > mx:
            mx = d["total"]
    chart.set_range(lv.chart.AXIS.PRIMARY_Y, 0, int(mx * 1.15) + 1)
    ser = chart.add_series(color, lv.chart.AXIS.PRIMARY_Y)
    for d in data:
        chart.set_next_value(ser, d["total"])
    return chart


def _stats(res):
    data = res.get("days", [])
    period = 0
    for d in data:
        period += d["total"]
    today = data[-1] if data else {"total": 0, "input": 0, "output": 0}
    avg = period // len(data) if data else 0
    return data, period, today, avg


def _panel(y0, header, color, res):
    """Compact half-height panel (used when both sources are shown)."""
    _label(header, lv.font_ascii_18, color, lv.ALIGN.TOP_LEFT, 8, y0 + 3)
    if not res or not res.get("ok"):
        _label(res.get("error", "No data") if res else "No data",
               lv.font_ascii_18, _C_GREY, lv.ALIGN.TOP_LEFT, 8, y0 + 40)
        return
    data, period, today, avg = _stats(res)
    _label("%dd %s" % (len(data), service.fmt_tokens(period)),
           lv.font_ascii_14, _C_GREY, lv.ALIGN.TOP_RIGHT, -8, y0 + 6)
    big = _label(service.fmt_tokens(today["total"]), lv.font_ascii_bold_28,
                 _C_WHITE, lv.ALIGN.TOP_LEFT, 8, y0 + 24)
    u = _label("today", lv.font_ascii_14, _C_GREY, lv.ALIGN.TOP_LEFT, 0, 0)
    u.align_to(big, lv.ALIGN.OUT_RIGHT_BOTTOM, 6, -2)
    _label("In %s  Out %s" % (service.fmt_tokens(today["input"]),
                              service.fmt_tokens(today["output"])),
           lv.font_ascii_14, color, lv.ALIGN.TOP_LEFT, 8, y0 + 58)
    _label("avg %s/day" % service.fmt_tokens(avg),
           lv.font_ascii_14, _C_GREY, lv.ALIGN.TOP_LEFT, 8, y0 + 78)
    if period <= 0:
        _label("no usage", lv.font_ascii_18, _C_GREY, lv.ALIGN.TOP_RIGHT, -40, y0 + 50)
        return
    _chart(data, color, 138, 80, lv.ALIGN.TOP_RIGHT, -6, y0 + 22)


def _full_panel(header, color, res):
    """Full-screen panel (used when only one source is configured)."""
    _label(header, lv.font_ascii_bold_22, color, lv.ALIGN.TOP_LEFT, 8, 6)
    if not res or not res.get("ok"):
        _show_message(header, res.get("error", "No data") if res else "No data")
        return
    data, period, today, avg = _stats(res)
    big = _label(service.fmt_tokens(today["total"]), lv.font_ascii_bold_28,
                 _C_WHITE, lv.ALIGN.TOP_LEFT, 8, 34)
    u = _label("today", lv.font_ascii_18, _C_GREY, lv.ALIGN.TOP_LEFT, 0, 0)
    u.align_to(big, lv.ALIGN.OUT_RIGHT_BOTTOM, 8, -2)
    _label("In %s  Out %s" % (service.fmt_tokens(today["input"]),
                              service.fmt_tokens(today["output"])),
           lv.font_ascii_14, color, lv.ALIGN.TOP_LEFT, 8, 70)
    _label("%dd total %s  /  %s per day" % (len(data), service.fmt_tokens(period),
                                            service.fmt_tokens(avg)),
           lv.font_ascii_14, _C_GREY, lv.ALIGN.TOP_LEFT, 8, 90)
    if period <= 0:
        _label("no usage in this period", lv.font_ascii_18, _C_GREY, lv.ALIGN.CENTER, 0, 40)
        return
    _chart(data, color, _SCR_WIDTH - 24, _SCR_HEIGHT - 130, lv.ALIGN.TOP_MID, 0, 106)
    if data:
        _label(data[0].get("label", ""), lv.font_ascii_14, _C_GREY, lv.ALIGN.BOTTOM_LEFT, 12, -2)
        _label("Today", lv.font_ascii_14, _C_GREY, lv.ALIGN.BOTTOM_RIGHT, -12, -2)


def _build_dashboard():
    if not _scr:
        return
    _clear()
    show_code = bool(_cfg().get("helper_url", ""))
    show_api = bool(_cfg().get("api_key", ""))
    if show_code and show_api:
        _panel(0, "Claude Code", _C_CODE, _code)
        _divider(118)
        _panel(121, "API", _C_API, _api)
    elif show_api:
        _full_panel("API", _C_API, _api)
    else:
        _full_panel("Claude Code", _C_CODE, _code)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

async def _refresh():
    global _code, _api, _last_updated
    helper = _cfg().get("helper_url", "")
    api_key = _cfg().get("api_key", "")
    n = _get_days()

    if not helper and not api_key:
        _show_message("Not configured",
                      "Set the Claude Code helper URL (and/or the Admin API key) "
                      "in the app settings.")
        return

    if _code is None and _api is None:
        _show_message("Loading ...", "Fetching usage.")

    _code = await local_service.fetch_usage(helper, n)   # returns quickly if helper empty
    _api = await service.fetch_usage(api_key, n)          # returns quickly if key empty
    _last_updated = clocktime.now()
    _build_dashboard()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def on_boot(apm):
    global _app_mgr
    _app_mgr = apm


async def on_start():
    global _scr, _last_updated
    if not _scr:
        _scr = lv.obj()
        _scr.set_style_bg_color(_C_BG, lv.PART.MAIN)
        _app_mgr.enter_root_page()
        lv.screen_load(_scr)

    if not net.connected():
        _show_message("No network",
                      "Please wait until the Dock's Wi-Fi is connected.")
        return

    if _code is not None or _api is not None:
        _build_dashboard()
    _last_updated = 0   # force refresh on the next foreground tick


async def on_stop():
    global _scr
    if _scr:
        _scr.clean()
        _scr.delete_async()
        _scr = None
        _app_mgr.leave_root_page()


async def on_running_foreground():
    if not net.connected():
        return
    now = clocktime.now()
    if now < 0:
        return
    if now - _last_updated < _UPDATE_INTERVAL:
        return
    await _refresh()
