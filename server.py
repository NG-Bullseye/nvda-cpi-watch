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
import investing
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
        return await bls.fetch_series(
            [bls.SERIES_HEADLINE, bls.SERIES_CORE,
             bls.SERIES_HEADLINE_SA, bls.SERIES_CORE_SA],
            start_year=today.year - 1,
            end_year=today.year,
        )
    raw = await cache_mod.cached("bls_latest", 6 * 3600, _fetch)
    h_nsa = bls.normalize(raw.get(bls.SERIES_HEADLINE, []))
    c_nsa = bls.normalize(raw.get(bls.SERIES_CORE, []))
    h_sa = bls.normalize(raw.get(bls.SERIES_HEADLINE_SA, []))
    c_sa = bls.normalize(raw.get(bls.SERIES_CORE_SA, []))
    return {
        "headline": {
            "nsa": h_nsa[0] if h_nsa else None,
            "sa": h_sa[0] if h_sa else None,
        },
        "core": {
            "nsa": c_nsa[0] if c_nsa else None,
            "sa": c_sa[0] if c_sa else None,
        },
        "convention_note": (
            "MoM market-headline = SA (what Bloomberg prints). "
            "YoY official BLS press-release = NSA (12-month change). "
            "Cross-check basis when comparing across sources."
        ),
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


def _reconcile_metric(per_source: dict[str, dict | None], key: str) -> dict:
    """Aggregate one metric (e.g. 'core_mom') across sources.

    Returns:
        {
          "forecast": <median of available forecasts, or single value, or None>,
          "previous": <median of available previous-prints, or None>,
          "by_source": {"tradingview": 0.4, "forexfactory": 0.3, "investing": 0.3},
          "spread_pp": 0.1,        # max - min across sources, None if <2 values
          "outlier_source": "tradingview",  # furthest from median, None if <3 values
          "n_sources": 3,
        }
    """
    by_source: dict[str, float] = {}
    prev_by_source: dict[str, float] = {}
    for src, data in per_source.items():
        if not isinstance(data, dict):
            continue
        block = data.get(key)
        if not isinstance(block, dict):
            continue
        fc = block.get("forecast")
        if isinstance(fc, (int, float)):
            by_source[src] = float(fc)
        prv = block.get("previous")
        if isinstance(prv, (int, float)):
            prev_by_source[src] = float(prv)

    values = sorted(by_source.values())
    n = len(values)
    if n == 0:
        median_fc = None
    elif n % 2 == 1:
        median_fc = values[n // 2]
    else:
        median_fc = round((values[n // 2 - 1] + values[n // 2]) / 2.0, 4)

    spread = round(max(values) - min(values), 4) if n >= 2 else None
    outlier = None
    if n >= 3 and median_fc is not None:
        # furthest source from median
        outlier = max(by_source.items(), key=lambda kv: abs(kv[1] - median_fc))[0]
        if abs(by_source[outlier] - median_fc) < 1e-9:
            outlier = None  # all values agree within precision

    prev_values = sorted(prev_by_source.values())
    if not prev_values:
        median_prev = None
    elif len(prev_values) % 2 == 1:
        median_prev = prev_values[len(prev_values) // 2]
    else:
        median_prev = round((prev_values[len(prev_values) // 2 - 1] + prev_values[len(prev_values) // 2]) / 2.0, 4)

    return {
        "forecast": median_fc,
        "previous": median_prev,
        "by_source": by_source,
        "spread_pp": spread,
        "outlier_source": outlier,
        "n_sources": n,
    }


async def _cpi_consensus() -> dict:
    """Aggregated market-consensus forecast for the next CPI release.

    Fetches three sources in parallel (TradingView, ForexFactory, Investing.com),
    reconciles per-metric: median forecast across sources, max-min spread, and
    outlier-source identification. All consensus values are SA-basis
    (Bloomberg-print convention).

    Core YoY is derived on SA-basis: sa_yoy = (latest_sa_idx * (1 + sa_mom/100))
    / sa_year_ago_idx - 1. No public NSA-MoM consensus exists.
    """
    nxt = bls.next_release_after(date.today())
    if not nxt:
        return {"error": "no upcoming release in schedule"}
    release_date = date.fromisoformat(nxt)

    async def _fetch_consensus():
        async def _safe(coro):
            try:
                return await coro
            except Exception as e:
                return {"_error": f"{type(e).__name__}: {e}"}
        tv, ff, inv = await asyncio.gather(
            _safe(tradingview.fetch_us_cpi_for_release(release_date)),
            _safe(forexfactory.fetch_us_cpi_for_release(release_date)),
            _safe(investing.fetch_us_cpi_for_release(release_date)),
        )
        return {"tradingview": tv, "forexfactory": ff, "investing": inv}

    per_source = await cache_mod.cached(f"consensus_multi_{nxt}", 900, _fetch_consensus)

    # Reconcile per metric
    reconciled = {
        "core_mom": _reconcile_metric(per_source, "core_mom"),
        "headline_mom": _reconcile_metric(per_source, "headline_mom"),
        "core_yoy": _reconcile_metric(per_source, "core_yoy"),
        "headline_yoy": _reconcile_metric(per_source, "headline_yoy"),
    }

    # Derive Core YoY on SA-basis from reconciled Core MoM forecast.
    core_mom_fc = reconciled["core_mom"]["forecast"]
    derived_core_yoy_sa = None
    derivation: dict[str, Any] = {"method": None}

    if core_mom_fc is not None:
        async def _fetch_bls_core_sa_history():
            today = date.today()
            return await bls.fetch_series(
                [bls.SERIES_CORE_SA],
                start_year=today.year - 2,
                end_year=today.year,
            )
        try:
            raw = await cache_mod.cached("bls_core_sa_history_2y", 6 * 3600, _fetch_bls_core_sa_history)
            sa_series = bls.normalize(raw.get(bls.SERIES_CORE_SA, []))
            if sa_series:
                latest = sa_series[0]
                latest_idx = latest["value"]
                print_month = release_date.month - 1 or 12
                print_year = release_date.year if release_date.month > 1 else release_date.year - 1
                year_ago = next(
                    (o for o in sa_series
                     if o["year"] == print_year - 1 and o["month"] == print_month),
                    None,
                )
                if year_ago is not None:
                    forecast_idx = latest_idx * (1 + core_mom_fc / 100.0)
                    derived_core_yoy_sa = round((forecast_idx / year_ago["value"] - 1) * 100, 2)
                    derivation = {
                        "method": "median_core_mom_forecast (SA) + bls_year_ago_idx (SA)",
                        "basis": "SA - clean unit-match with consensus Core MoM",
                        "latest_core_sa_idx": latest_idx,
                        "latest_period": f"{latest['year']}-{latest['month']:02d}",
                        "year_ago_core_sa_idx": year_ago["value"],
                        "year_ago_period": f"{year_ago['year']}-{year_ago['month']:02d}",
                        "core_mom_forecast_pct": core_mom_fc,
                        "implied_forecast_idx": round(forecast_idx, 3),
                    }
                else:
                    derivation["method"] = "no SA year-ago BLS data point yet"
        except Exception as e:
            derivation["method"] = f"derivation failed: {e}"

    # Build legacy-shape blocks for downstream tools (cpi_trade_brief reads these).
    def _legacy_block(metric_key: str) -> dict:
        rec = reconciled[metric_key]
        return {
            "previous": rec["previous"],
            "forecast": rec["forecast"],
            "actual": None,
            "period": None,
            "date_utc": None,
            "title": f"Reconciled {metric_key}",
            "unit": "%",
            "source": "median(tradingview,forexfactory,investing)",
        }

    return {
        "release_date_et": nxt,
        "basis_note": "All consensus values are SA-basis (Bloomberg-print convention). Forecast = median across available sources.",
        "headline_yoy": _legacy_block("headline_yoy"),
        "headline_mom": _legacy_block("headline_mom"),
        "core_mom": _legacy_block("core_mom"),
        "core_yoy": _legacy_block("core_yoy"),
        "core_yoy_derived_pct_sa": derived_core_yoy_sa,
        "core_yoy_derivation": derivation,
        "reconciliation": reconciled,
        "raw_per_source": per_source,
    }


async def _cpi_trade_brief() -> dict:
    """Aggregated brief for the next CPI release.

    Structure:
      - primary_signal_core_mom: Core MoM on SA basis. Clean unit-match across
        all three sources (BLS-SA previous print, TradingView SA forecast,
        Cleveland Fed SA nowcast). This is the value Bloomberg-style traders
        read off the print and the Fed-policy-relevant short-term signal.
      - secondary_signal_headline_mom: same structure, headline MoM (SA).
      - context_core_yoy: SA-derivation + NSA-official-press-release figure
        with explicit basis labels (no mixing).
      - context_headline_yoy: previous print on both bases + forecast/nowcast.
    """
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

    # ─── Primary: Core MoM (SA - Bloomberg-print + Fed-policy convention) ─────
    core_mom_prev_sa = _g(latest, "core", "sa", "mom_pct")
    core_mom_fc = _g(consensus, "core_mom", "forecast")
    core_mom_nowcast = _g(nowcast, "core", "mom_pct")

    # ─── Secondary: Headline MoM (SA) ─────────────────────────────────────────
    head_mom_prev_sa = _g(latest, "headline", "sa", "mom_pct")
    head_mom_fc = _g(consensus, "headline_mom", "forecast")
    head_mom_nowcast = _g(nowcast, "headline", "mom_pct")

    # ─── Context: Core YoY (SA derivation + NSA official figure) ──────────────
    core_yoy_sa_prev = _g(latest, "core", "sa", "yoy_pct")
    core_yoy_sa_fc_derived = consensus.get("core_yoy_derived_pct_sa")
    core_yoy_nsa_prev = _g(latest, "core", "nsa", "yoy_pct")
    core_yoy_nowcast = _g(nowcast, "core", "yoy_pct")  # CL Fed convention: NSA

    # ─── Context: Headline YoY ────────────────────────────────────────────────
    head_yoy_sa_prev = _g(latest, "headline", "sa", "yoy_pct")
    head_yoy_nsa_prev = _g(latest, "headline", "nsa", "yoy_pct")
    head_yoy_fc = _g(consensus, "headline_yoy", "forecast")  # SA (TradingView)
    head_yoy_nowcast = _g(nowcast, "headline", "yoy_pct")    # NSA (CL Fed)

    recon = consensus.get("reconciliation") or {}
    def _q(metric: str) -> dict:
        r = recon.get(metric) or {}
        return {
            "by_source": r.get("by_source"),
            "spread_pp": r.get("spread_pp"),
            "outlier_source": r.get("outlier_source"),
            "n_sources": r.get("n_sources"),
        }
    consensus_quality = {
        "note": "Forecast = median across TradingView, ForexFactory, Investing.com. spread_pp > 0.05 indicates source disagreement.",
        "core_mom": _q("core_mom"),
        "headline_mom": _q("headline_mom"),
        "core_yoy": _q("core_yoy"),
        "headline_yoy": _q("headline_yoy"),
    }

    return {
        "release_date_et": nxt,
        "release_time_de": "14:30 MEZ Sommerzeit (= 08:30 ET)",
        "consensus_quality": consensus_quality,
        "primary_signal_core_mom": {
            "basis": "SA (Bloomberg-print + Fed-policy convention)",
            "previous_print": core_mom_prev_sa,
            "forecast": core_mom_fc,
            "nowcast": core_mom_nowcast,
            "forecast_vs_previous_pp": _spread(core_mom_fc, core_mom_prev_sa),
            "nowcast_vs_forecast_pp": _spread(core_mom_nowcast, core_mom_fc),
            "interpretation": (
                "Print BELOW forecast tends to be bullish for rate-sensitive Tech (NVDA, etc.); "
                "ABOVE forecast tends to be bearish. Nowcast-vs-forecast gap = "
                "asymmetric-surprise skew. DATA ONLY - not a recommendation."
            ),
        },
        "secondary_signal_headline_mom": {
            "basis": "SA",
            "previous_print": head_mom_prev_sa,
            "forecast": head_mom_fc,
            "nowcast": head_mom_nowcast,
            "forecast_vs_previous_pp": _spread(head_mom_fc, head_mom_prev_sa),
            "nowcast_vs_forecast_pp": _spread(head_mom_nowcast, head_mom_fc),
        },
        "context_core_yoy": {
            "sa_basis": {
                "previous_print": core_yoy_sa_prev,
                "forecast_derived": core_yoy_sa_fc_derived,
                "note": "SA_MoM_forecast compounded onto SA year-ago index. Clean unit-match within block.",
            },
            "nsa_basis": {
                "previous_print_official": core_yoy_nsa_prev,
                "nowcast": core_yoy_nowcast,
                "note": (
                    "BLS press-release '12-month change' is NSA. Cleveland Fed YoY follows same NSA "
                    "convention. No public NSA-MoM consensus -> no NSA forecast derivable."
                ),
            },
            "_derivation": consensus.get("core_yoy_derivation"),
        },
        "context_headline_yoy": {
            "previous_print_nsa": head_yoy_nsa_prev,
            "previous_print_sa": head_yoy_sa_prev,
            "forecast_sa": head_yoy_fc,
            "nowcast_nsa": head_yoy_nowcast,
        },
        "sources": [
            "BLS (NSA: CUUR*, SA: CUSR*)",
            "TradingView (SA basis)",
            "ForexFactory (SA basis, fallback)",
            "Cleveland Fed (MoM=SA, YoY=NSA by convention)",
        ],
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
