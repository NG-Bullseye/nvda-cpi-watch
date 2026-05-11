"""Investing.com economic-calendar per-event-page scraper (no auth).

Investing.com publishes a dedicated HTML page per economic indicator with
release history including Forecast + Previous + Actual. We scrape the first
data row (= next/most-recent release) for each of the four US CPI series.

Event IDs (verified 2026-05):
    69  = U.S. Consumer Price Index (CPI) MoM      -> headline_mom
    56  = U.S. Core Consumer Price Index (CPI) MoM -> core_mom
    733 = U.S. Consumer Price Index (CPI) YoY      -> headline_yoy
    736 = U.S. Core Consumer Price Index (CPI) YoY -> core_yoy

Returns the same shape as tradingview.fetch_us_cpi_for_release() so the
aggregator in server.py can treat all sources uniformly.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Any

import httpx
from bs4 import BeautifulSoup

US_CPI_EVENTS: dict[str, tuple[int, str]] = {
    "headline_mom": (69,  "U.S. CPI MoM"),
    "core_mom":     (56,  "U.S. Core CPI MoM"),
    "headline_yoy": (733, "U.S. CPI YoY"),
    "core_yoy":     (736, "U.S. Core CPI YoY"),
}

URL_TPL = "https://www.investing.com/economic-calendar/-{eid}"
URL_TPL_FALLBACK = "https://www.investing.com/economic-calendar/cpi-{eid}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0",
}

PCT_RE = re.compile(r"-?\d+\.\d+")
DATE_RE = re.compile(r"^([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})")


def _parse_pct(s: str) -> float | None:
    if not s:
        return None
    m = PCT_RE.search(s)
    return float(m.group(0)) if m else None


def _matches_release_date(row_date_text: str, target: date) -> bool:
    """Investing.com row date looks like 'May 12, 2026 (Apr)'. Match to target."""
    m = DATE_RE.match(row_date_text or "")
    if not m:
        return False
    mon_name, day, year = m.group(1), int(m.group(2)), int(m.group(3))
    months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
              "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
    return (months.get(mon_name) == target.month
            and day == target.day
            and year == target.year)


async def _fetch_one(client: httpx.AsyncClient, eid: int) -> dict | None:
    """Return dict {previous, forecast, actual, period, date_utc, title, unit, source}
    for the first row of the event-history table, or None on failure."""
    for url in (URL_TPL.format(eid=eid), URL_TPL_FALLBACK.format(eid=eid)):
        try:
            r = await client.get(url, headers=HEADERS)
            if r.status_code != 200:
                continue
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
        for tbl in soup.find_all("table"):
            tbody = tbl.find("tbody")
            if not tbody:
                continue
            tr = tbody.find("tr")
            if not tr:
                continue
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            # Expected: [date, time, actual, forecast, previous]
            if len(cells) < 5 or not DATE_RE.match(cells[0] or ""):
                continue
            return {
                "previous": _parse_pct(cells[4]),
                "forecast": _parse_pct(cells[3]),
                "actual": _parse_pct(cells[2]),
                "period": cells[0],
                "date_utc": None,
                "title": title,
                "unit": "%",
                "source": "investing",
            }
        return None
    return None


async def fetch_us_cpi_for_release(release_date: date) -> dict[str, dict]:
    """Returns same shape as tradingview.fetch_us_cpi_for_release()."""
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        tasks = {k: _fetch_one(client, eid) for k, (eid, _) in US_CPI_EVENTS.items()}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    out: dict[str, dict] = {}
    for key, res in zip(tasks.keys(), results):
        if isinstance(res, Exception) or res is None:
            continue
        # Sanity: row date must match release_date (skip stale rows)
        if not _matches_release_date(res.get("period") or "", release_date):
            continue
        out[key] = res
    return out
