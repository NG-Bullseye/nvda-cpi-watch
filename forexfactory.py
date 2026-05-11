"""ForexFactory calendar fallback (third-party feed, faireconomy.media).
Genutzt nur wenn TradingView nicht liefert. Deckt nur Headline-YoY + MoM
und Core MoM ab - Core YoY liefert FF nicht.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import httpx

URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def _parse_pct(s: Any) -> float | None:
    if not isinstance(s, str):
        return None
    s = s.strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


async def fetch_us_cpi_for_release(release_date: date) -> dict[str, dict]:
    """Returns same shape as tradingview.fetch_us_cpi_for_release()."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(URL, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.json()

    rd = release_date.isoformat()
    out: dict[str, dict] = {}
    for ev in data:
        if (ev.get("country") or "").upper() != "USD":
            continue
        d = (ev.get("date") or "")[:10]
        if d != rd:
            continue
        title = ev.get("title") or ""
        tl = title.lower()
        if "cpi" not in tl:
            continue
        series = "core" if "core" in tl else "headline"
        if "y/y" in tl or "yoy" in tl:
            freq = "yoy"
        elif "m/m" in tl or "mom" in tl:
            freq = "mom"
        else:
            continue
        key = f"{series}_{freq}"
        if key in out:
            continue
        out[key] = {
            "previous": _parse_pct(ev.get("previous")),
            "forecast": _parse_pct(ev.get("forecast")),
            "actual": _parse_pct(ev.get("actual")),
            "period": None,
            "date_utc": ev.get("date"),
            "title": title,
            "unit": "%",
            "source": "forexfactory",
        }
    return out
