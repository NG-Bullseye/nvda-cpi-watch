#!/usr/bin/env python3
"""nvda-cpi-watch MCP Server (stdio).

Tools fuer NVDA-Earnings + US-CPI: historische Werte, Forecasts, Nowcasts,
und ein aggregierter Trade-Brief. Daten kommen aus BLS (frei),
Finnhub (free tier, Key noetig) und Cleveland Fed (HTML-scrape).

Composition Root: dieses File haelt nur Tool-Registry + Routing. Echte
Logik lebt in bls.py / finnhub.py / clevelandfed.py.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

load_dotenv(Path(__file__).parent / ".env")

import bls
import clevelandfed
import finnhub
import cache as cache_mod

app = Server("nvda-cpi-watch")


# ─── Tool Definitions ─────────────────────────────────────────────────────────

TOOLS = [
    types.Tool(
        name="cpi_latest",
        description="Latest US CPI: Headline + Core, with MoM and YoY percentage change.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="cpi_history",
        description="US CPI history, monthly. Returns Headline + Core values plus MoM/YoY.",
        inputSchema={
            "type": "object",
            "properties": {
                "months": {"type": "integer", "minimum": 1, "maximum": 60, "default": 12},
            },
        },
    ),
    types.Tool(
        name="cpi_next_release",
        description="Date (US Eastern) of the next BLS CPI release.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="cpi_forecast",
        description="Market consensus forecast for the next CPI release (Headline + Core if available). Source: Finnhub economic calendar. Requires FINNHUB_API_KEY.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="cpi_nowcast",
        description="Cleveland Fed Inflation Nowcasting (live model estimate for current/next month CPI + Core CPI, MoM and YoY).",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="cpi_trade_brief",
        description=(
            "Aggregated brief for the next CPI release: Core + Headline values for "
            "Forecast vs Nowcast vs Previous, surprise potential, release timing. "
            "INFORMATIONAL ONLY - not a trade recommendation."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="nvda_earnings_history",
        description="NVIDIA historical quarterly earnings (most recent first): date, EPS estimate vs actual, revenue. Requires FINNHUB_API_KEY.",
        inputSchema={
            "type": "object",
            "properties": {
                "quarters": {"type": "integer", "minimum": 1, "maximum": 12, "default": 4},
            },
        },
    ),
    types.Tool(
        name="nvda_earnings_next",
        description="Next NVIDIA earnings report: date, before/after market close, estimates. Requires FINNHUB_API_KEY.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


# ─── Tool Implementations ─────────────────────────────────────────────────────

async def _cpi_latest() -> dict:
    async def _fetch():
        today = date.today()
        data = await bls.fetch_series(
            [bls.SERIES_HEADLINE, bls.SERIES_CORE],
            start_year=today.year - 1,
            end_year=today.year,
        )
        return data
    raw = await cache_mod.cached("bls_latest", 6 * 3600, _fetch)
    headline = bls.normalize(raw.get(bls.SERIES_HEADLINE, []))
    core = bls.normalize(raw.get(bls.SERIES_CORE, []))
    return {
        "headline": headline[0] if headline else None,
        "core": core[0] if core else None,
        "source": "BLS API v2",
    }


async def _cpi_history(months: int) -> dict:
    async def _fetch():
        today = date.today()
        years_needed = max(2, (months // 12) + 2)
        data = await bls.fetch_series(
            [bls.SERIES_HEADLINE, bls.SERIES_CORE],
            start_year=today.year - years_needed,
            end_year=today.year,
        )
        return data
    raw = await cache_mod.cached(f"bls_history_{months}", 6 * 3600, _fetch)
    headline = bls.normalize(raw.get(bls.SERIES_HEADLINE, []))[:months]
    core = bls.normalize(raw.get(bls.SERIES_CORE, []))[:months]
    return {"headline": headline, "core": core, "source": "BLS API v2"}


async def _cpi_next_release() -> dict:
    nxt = bls.next_release_after(date.today())
    return {
        "next_release_date_et": nxt,
        "release_time_et": "08:30",
        "release_time_de": "14:30 (Sommerzeit) / 15:30 (Winterzeit)",
        "source": "BLS schedule (https://www.bls.gov/schedule/news_release/cpi.htm)",
    }


async def _cpi_forecast() -> dict:
    nxt = bls.next_release_after(date.today())
    if not nxt:
        return {"error": "no upcoming release in schedule"}
    release_date = date.fromisoformat(nxt)

    async def _fetch():
        events = await finnhub.economic_calendar(
            release_date - timedelta(days=1),
            release_date + timedelta(days=1),
        )
        return finnhub.filter_us_cpi(events)

    try:
        events = await cache_mod.cached(f"finnhub_cpi_forecast_{nxt}", 1800, _fetch)
    except finnhub.MissingKey as e:
        return {"error": str(e), "release_date": nxt}

    headline = None
    core = None
    for ev in events:
        name = (ev.get("event") or "").lower()
        entry = {
            "estimate": ev.get("estimate"),
            "previous": ev.get("prev"),
            "actual": ev.get("actual"),
            "unit": ev.get("unit"),
            "event": ev.get("event"),
            "time": ev.get("time"),
        }
        if "core" in name:
            core = entry
        elif headline is None and "cpi" in name:
            headline = entry
    return {
        "release_date": nxt,
        "headline": headline,
        "core": core,
        "all_events_raw": events,
        "source": "Finnhub /calendar/economic",
    }


async def _cpi_nowcast() -> dict:
    async def _fetch():
        return await clevelandfed.fetch_nowcast()
    return await cache_mod.cached("cleveland_nowcast", 3 * 3600, _fetch)


async def _cpi_trade_brief() -> dict:
    nxt = bls.next_release_after(date.today())
    latest = await _cpi_latest()
    forecast = await _cpi_forecast()
    try:
        nowcast = await _cpi_nowcast()
    except Exception as e:
        nowcast = {"error": str(e)}

    def _surprise(forecast_v, nowcast_v):
        if forecast_v is None or nowcast_v is None:
            return None
        return round(nowcast_v - forecast_v, 2)

    fc_core = (forecast.get("core") or {}).get("estimate") if isinstance(forecast.get("core"), dict) else None
    fc_head = (forecast.get("headline") or {}).get("estimate") if isinstance(forecast.get("headline"), dict) else None
    prev_core = (forecast.get("core") or {}).get("previous") if isinstance(forecast.get("core"), dict) else None
    prev_head = (forecast.get("headline") or {}).get("previous") if isinstance(forecast.get("headline"), dict) else None

    nc_core_yoy = (nowcast.get("core") or {}).get("yoy_pct") if isinstance(nowcast.get("core"), dict) else None
    nc_head_yoy = (nowcast.get("headline") or {}).get("yoy_pct") if isinstance(nowcast.get("headline"), dict) else None

    return {
        "release_date_et": nxt,
        "release_time_de": "14:30 MEZ Sommerzeit",
        "headline": {
            "previous": prev_head,
            "forecast": fc_head,
            "nowcast_yoy": nc_head_yoy,
            "surprise_potential_pct_points": _surprise(fc_head, nc_head_yoy),
            "latest_actual_yoy_pct": (latest.get("headline") or {}).get("yoy_pct"),
        },
        "core": {
            "previous": prev_core,
            "forecast": fc_core,
            "nowcast_yoy": nc_core_yoy,
            "surprise_potential_pct_points": _surprise(fc_core, nc_core_yoy),
            "latest_actual_yoy_pct": (latest.get("core") or {}).get("yoy_pct"),
        },
        "interpretation_hint": (
            "Core CPI is the key reading for Fed policy expectations and Big-Tech sensitivity. "
            "Print BELOW forecast tends to be bullish for rate-sensitive Tech (NVDA, etc.); "
            "print ABOVE forecast tends to be bearish. Surprise magnitude drives move size. "
            "DATA ONLY - not a recommendation."
        ),
        "sources": ["BLS", "Finnhub", "Cleveland Fed"],
    }


async def _nvda_earnings_history(quarters: int) -> dict:
    async def _fetch():
        return await finnhub.stock_earnings("NVDA", limit=max(quarters, 4))
    try:
        rows = await cache_mod.cached(f"nvda_earnings_history_{quarters}", 3600, _fetch)
    except finnhub.MissingKey as e:
        return {"error": str(e)}
    return {"quarters": rows[:quarters], "source": "Finnhub /stock/earnings"}


async def _nvda_earnings_next() -> dict:
    async def _fetch():
        return await finnhub.next_nvda_earnings()
    try:
        ev = await cache_mod.cached("nvda_earnings_next", 3600, _fetch)
    except finnhub.MissingKey as e:
        return {"error": str(e)}
    if not ev:
        return {"error": "no upcoming NVDA earnings event in horizon"}
    hour_map = {"bmo": "before market open", "amc": "after market close", "dmh": "during market hours"}
    return {
        "date": ev.get("date"),
        "hour": ev.get("hour"),
        "timing": hour_map.get(ev.get("hour", ""), ev.get("hour")),
        "eps_estimate": ev.get("epsEstimate"),
        "revenue_estimate": ev.get("revenueEstimate"),
        "year": ev.get("year"),
        "quarter": ev.get("quarter"),
        "source": "Finnhub /calendar/earnings",
    }


# ─── Tool Dispatch ────────────────────────────────────────────────────────────

DISPATCH = {
    "cpi_latest": lambda args: _cpi_latest(),
    "cpi_history": lambda args: _cpi_history(int(args.get("months", 12))),
    "cpi_next_release": lambda args: _cpi_next_release(),
    "cpi_forecast": lambda args: _cpi_forecast(),
    "cpi_nowcast": lambda args: _cpi_nowcast(),
    "cpi_trade_brief": lambda args: _cpi_trade_brief(),
    "nvda_earnings_history": lambda args: _nvda_earnings_history(int(args.get("quarters", 4))),
    "nvda_earnings_next": lambda args: _nvda_earnings_next(),
}


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    handler = DISPATCH.get(name)
    if not handler:
        return [types.TextContent(type="text", text=json.dumps({"error": f"unknown tool: {name}"}))]
    try:
        result = await handler(arguments or {})
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}
    return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


# ─── Entrypoint ───────────────────────────────────────────────────────────────

async def main() -> None:
    async with stdio_server() as (reader, writer):
        await app.run(reader, writer, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
