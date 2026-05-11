"""TradingView Economic Calendar client (no auth, public widget endpoint).
Source: https://economic-calendar.tradingview.com/events

Liefert pro Event: title, indicator, date, period, previous, forecast,
actual, unit, currency, importance, ticker. Ohne API-Key, ohne Quota
(fair-use). Wir filtern auf US-Inflation-Events (Headline + Core,
MoM + YoY).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

URL = "https://economic-calendar.tradingview.com/events"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "Accept": "application/json",
}


async def fetch_events(from_date: date, to_date: date, country: str = "US") -> list[dict]:
    params = {
        "from": from_date.strftime("%Y-%m-%dT00:00:00.000Z"),
        "to": (to_date + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000Z"),
        "countries": country,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(URL, params=params, headers=HEADERS)
        r.raise_for_status()
        body = r.json()
    if body.get("status") != "ok":
        raise RuntimeError(f"TradingView API status={body.get('status')}: {body}")
    return body.get("result") or []


def _classify(title: str) -> tuple[str | None, str | None]:
    """Return (series, frequency) for a CPI/inflation event.
    series in {'headline', 'core'}, frequency in {'mom', 'yoy'}.
    Returns (None, None) if not a CPI event.
    """
    t = title.lower()
    if "inflation rate" not in t and "cpi" not in t and "consumer price" not in t:
        return (None, None)
    series = "core" if "core" in t else "headline"
    if "yoy" in t or "y/y" in t or "year-over-year" in t:
        freq = "yoy"
    elif "mom" in t or "m/m" in t or "month-over-month" in t:
        freq = "mom"
    else:
        return (None, None)
    return (series, freq)


def filter_us_cpi(events: list[dict]) -> dict[str, dict]:
    """Reduce US events to a flat keyed dict:
        {'headline_yoy': {...}, 'headline_mom': {...}, 'core_yoy': {...}, 'core_mom': {...}}
    Each value: {previous, forecast, actual, period, date_utc, source: 'tradingview'}
    """
    out: dict[str, dict] = {}
    for ev in events:
        if (ev.get("currency") or "").upper() != "USD":
            continue
        title = ev.get("title") or ""
        series, freq = _classify(title)
        if series is None:
            continue
        key = f"{series}_{freq}"
        # Prefer the first occurrence per key (TradingView usually has only one per release).
        if key in out:
            continue
        out[key] = {
            "previous": ev.get("previous"),
            "forecast": ev.get("forecast"),
            "actual": ev.get("actual"),
            "period": ev.get("period"),
            "date_utc": ev.get("date"),
            "title": title,
            "unit": ev.get("unit"),
            "source": "tradingview",
        }
    return out


async def fetch_us_cpi_for_release(release_date: date) -> dict[str, dict]:
    """Wrapper: fetch ±1 day around release_date, filter to US CPI events."""
    events = await fetch_events(release_date - timedelta(days=1), release_date + timedelta(days=1))
    return filter_us_cpi(events)
