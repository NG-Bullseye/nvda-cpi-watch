#!/usr/bin/env python3
"""nvda-cpi-watch MCP Server (stdio).

Tools fuer NVDA-Earnings + US-CPI: historische Werte, Forecasts, Nowcasts,
und ein aggregierter Trade-Brief. Daten kommen aus BLS (frei),
Finnhub (free tier, Key noetig), Cleveland Fed (HTML-scrape), TradingView
(public calendar, kein Key), ForexFactory (Fallback).

Composition Root: dieses File haelt nur Tool-Registry + Routing. Echte
Logik lebt in bls.py / finnhub.py / clevelandfed.py / tradingview.py /
forexfactory.py.
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
import tradingview
import forexfactory
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
        description="DEPRECATED - use cpi_consensus. Finnhub economic calendar (returns index level only, no YoY consensus).",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="cpi_consensus",
        description=(
            "Market consensus forecast for the next CPI release: Headline + Core, "
            "MoM and YoY. Core YoY is derived from Core MoM forecast + BLS year-ago "
            "Core CPI index (no free API publishes Core YoY directly). Primary source "
            "TradingView (no key); fallback ForexFactory."
        ),
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


async def _cpi_consensus() -> dict:
    """Aggregated market-consensus forecast for the next CPI release.

    - Headline YoY/MoM + Core MoM: TradingView (primary), ForexFactory (fallback).
    - Core YoY: derived from Core MoM forecast + BLS year-ago Core index.
      Formula: core_yoy_forecast = (latest_core_idx * (1 + mom/100)) / year_ago_idx - 1
      Reason: no free API publishes Core CPI YoY consensus directly.
    """
    nxt = bls.next_release_after(date.today())
    if not nxt:
        return {"error": "no upcoming release in schedule"}
    release_date = date.fromisoformat(nxt)

    async def _fetch_consensus():
        try:
            tv = await tradingview.fetch_us_cpi_for_release(release_date)
            if tv:
                return tv
        except Exception as e:
            tv = {"_error": f"tradingview failed: {e}"}
        try:
            ff = await forexfactory.fetch_us_cpi_for_release(release_date)
            ff["_source_chain"] = "tradingview_failed,forexfactory_fallback"
            return ff
        except Exception as e:
            return {"_error": f"both sources failed: tv={tv}; ff={e}"}

    consensus = await cache_mod.cached(f"consensus_{nxt}", 1800, _fetch_consensus)

    # Derive Core YoY if we have Core MoM forecast + enough BLS history.
    core_mom = consensus.get("core_mom", {}) or {}
    core_mom_fc = core_mom.get("forecast")
    derived_core_yoy = None
    derivation: dict[str, Any] = {"method": None}

    if core_mom_fc is not None:
        async def _fetch_bls_core_history():
            today = date.today()
            return await bls.fetch_series(
                [bls.SERIES_CORE],
                start_year=today.year - 2,
                end_year=today.year,
            )
        try:
            raw = await cache_mod.cached("bls_core_history_2y", 6 * 3600, _fetch_bls_core_history)
            core_series = bls.normalize(raw.get(bls.SERIES_CORE, []))
            if core_series:
                # Latest = newest reported (= month BEFORE the release_date typically).
                latest = core_series[0]
                latest_idx = latest["value"]
                # Print period = the month the release REPORTS ON, i.e. the calendar month
                # before the release date (April release -> April CPI, May release -> April CPI etc.).
                # CPI releases publish data for the prior calendar month.
                print_month = release_date.month - 1 or 12
                print_year = release_date.year if release_date.month > 1 else release_date.year - 1
                # Year-ago = same print-month, one year earlier.
                year_ago = next(
                    (o for o in core_series
                     if o["year"] == print_year - 1 and o["month"] == print_month),
                    None,
                )
                if year_ago is not None:
                    forecast_idx = latest_idx * (1 + core_mom_fc / 100.0)
                    derived_core_yoy = round((forecast_idx / year_ago["value"] - 1) * 100, 2)
                    derivation = {
                        "method": "core_mom_forecast + bls_year_ago_index",
                        "latest_core_idx": latest_idx,
                        "latest_period": f"{latest['year']}-{latest['month']:02d}",
                        "year_ago_core_idx": year_ago["value"],
                        "year_ago_period": f"{year_ago['year']}-{year_ago['month']:02d}",
                        "core_mom_forecast_pct": core_mom_fc,
                        "implied_forecast_idx": round(forecast_idx, 3),
                    }
                else:
                    derivation["method"] = "no year-ago BLS data point yet"
        except Exception as e:
            derivation["method"] = f"derivation failed: {e}"

    return {
        "release_date_et": nxt,
        "headline_yoy": consensus.get("headline_yoy"),
        "headline_mom": consensus.get("headline_mom"),
        "core_mom": consensus.get("core_mom"),
        "core_yoy": consensus.get("core_yoy"),  # often None - free APIs don't publish it
        "core_yoy_derived_pct": derived_core_yoy,
        "core_yoy_derivation": derivation,
        "raw_consensus": consensus,
    }


async def _cpi_trade_brief() -> dict:
    nxt = bls.next_release_after(date.today())
    latest = await _cpi_latest()
    consensus = await _cpi_consensus()
    try:
        nowcast = await _cpi_nowcast()
    except Exception as e:
        nowcast = {"error": str(e)}

    def _g(d: dict | None, *path):
        for p in path:
            if not isinstance(d, dict):
                return None
            d = d.get(p)
        return d

    def _spread(a, b):
        if a is None or b is None:
            return None
        return round(a - b, 2)

    # Headline YoY
    head_prev = _g(consensus, "headline_yoy", "previous") or _g(latest, "headline", "yoy_pct")
    head_fc = _g(consensus, "headline_yoy", "forecast")
    head_nowcast = _g(nowcast, "headline", "yoy_pct")

    # Core YoY: consensus from free APIs is usually None - use derived
    core_prev = _g(consensus, "core_yoy", "previous") or _g(latest, "core", "yoy_pct")
    core_fc_direct = _g(consensus, "core_yoy", "forecast")
    core_fc_derived = consensus.get("core_yoy_derived_pct")
    core_fc = core_fc_direct if core_fc_direct is not None else core_fc_derived
    core_nowcast = _g(nowcast, "core", "yoy_pct")

    # Core MoM (the value Bloomberg-style traders actually watch on print)
    core_mom_prev = _g(consensus, "core_mom", "previous")
    core_mom_fc = _g(consensus, "core_mom", "forecast")

    return {
        "release_date_et": nxt,
        "release_time_de": "14:30 MEZ Sommerzeit (= 08:30 ET)",
        "headline_yoy": {
            "previous": head_prev,
            "forecast": head_fc,
            "nowcast": head_nowcast,
            "forecast_vs_previous_pp": _spread(head_fc, head_prev),
            "nowcast_vs_forecast_pp": _spread(head_nowcast, head_fc),
        },
        "core_yoy": {
            "previous": core_prev,
            "forecast": core_fc,
            "forecast_source": "derived (core_mom + bls)" if core_fc_direct is None and core_fc_derived is not None else ("consensus_api" if core_fc_direct is not None else None),
            "nowcast": core_nowcast,
            "forecast_vs_previous_pp": _spread(core_fc, core_prev),
            "nowcast_vs_forecast_pp": _spread(core_nowcast, core_fc),
            "_derivation": consensus.get("core_yoy_derivation"),
        },
        "core_mom": {
            "previous": core_mom_prev,
            "forecast": core_mom_fc,
            "note": "Core MoM is the value Bloomberg traders read directly off the print.",
        },
        "interpretation_hint": (
            "Core CPI is the key reading for Fed policy expectations and Big-Tech sensitivity. "
            "Print BELOW forecast tends to be bullish for rate-sensitive Tech (NVDA, etc.); "
            "print ABOVE forecast tends to be bearish. Surprise magnitude drives move size. "
            "Cross-check Core MoM (Bloomberg headline) and Core YoY (Fed-trajectory). "
            "DATA ONLY - not a recommendation."
        ),
        "sources": ["BLS", "TradingView", "ForexFactory (fallback)", "Cleveland Fed"],
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
    "cpi_consensus": lambda args: _cpi_consensus(),
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
