"""Finnhub client. Earnings calendar + historical earnings + economic calendar (CPI forecast)."""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import httpx

BASE = "https://finnhub.io/api/v1"


class MissingKey(RuntimeError):
    pass


def _key() -> str:
    k = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not k:
        raise MissingKey("FINNHUB_API_KEY not set in environment / .env")
    return k


async def _get(path: str, params: dict[str, Any]) -> Any:
    params = {**params, "token": _key()}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()


async def earnings_calendar(symbol: str, from_date: date, to_date: date) -> list[dict]:
    body = await _get("/calendar/earnings", {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "symbol": symbol,
    })
    return body.get("earningsCalendar", []) or []


async def stock_earnings(symbol: str, limit: int = 8) -> list[dict]:
    """Historical earnings (most recent first). limit=quarters."""
    body = await _get("/stock/earnings", {"symbol": symbol, "limit": limit})
    return body if isinstance(body, list) else []


async def economic_calendar(from_date: date, to_date: date) -> list[dict]:
    body = await _get("/calendar/economic", {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
    })
    return body.get("economicCalendar", []) or []


def filter_us_cpi(events: list[dict]) -> list[dict]:
    """Reduce economic calendar to US CPI-related events (Headline + Core)."""
    out = []
    for ev in events:
        country = (ev.get("country") or "").upper()
        if country not in ("US", "USA"):
            continue
        name = (ev.get("event") or "").lower()
        if "cpi" not in name and "consumer price" not in name:
            continue
        out.append(ev)
    return out


async def next_nvda_earnings() -> dict | None:
    """Look 120 days forward for next NVDA earnings event."""
    today = date.today()
    horizon = today + timedelta(days=120)
    events = await earnings_calendar("NVDA", today, horizon)
    if not events:
        return None
    events.sort(key=lambda e: e.get("date", "9999-99-99"))
    return events[0]
