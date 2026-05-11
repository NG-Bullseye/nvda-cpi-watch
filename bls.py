"""BLS API v2 client. Headline CPI (CUUR0000SA0) + Core CPI (CUUR0000SA0L1E)."""
from __future__ import annotations

import os
from datetime import date
from typing import Any

import httpx

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
# NSA (Not Seasonally Adjusted) - BLS press-release "12-month change" YoY basis.
SERIES_HEADLINE = "CUUR0000SA0"
SERIES_CORE = "CUUR0000SA0L1E"
# SA (Seasonally Adjusted) - Bloomberg/Reuters MoM headline basis; market consensus
# from TradingView quotes SA values. Use for MoM comparisons.
SERIES_HEADLINE_SA = "CUSR0000SA0"
SERIES_CORE_SA = "CUSR0000SA0L1E"


def _api_key() -> str | None:
    key = os.environ.get("BLS_API_KEY")
    return key or None


async def fetch_series(series_ids: list[str], start_year: int, end_year: int) -> dict[str, list[dict]]:
    """Fetch one or more series. Returns {series_id: [observations]}.
    Each observation: {year, period, periodName, value, footnotes, ...}.
    """
    payload: dict[str, Any] = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    key = _api_key()
    if key:
        payload["registrationkey"] = key

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(BLS_URL, json=payload)
        r.raise_for_status()
        body = r.json()

    if body.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API error: {body.get('message', body)}")

    out: dict[str, list[dict]] = {}
    for series in body.get("Results", {}).get("series", []):
        out[series["seriesID"]] = series.get("data", [])
    return out


def _period_to_month(period: str) -> int:
    # BLS uses M01..M12; M13 = annual (skip)
    return int(period[1:])


def _yoy(curr: float, year_ago: float | None) -> float | None:
    if year_ago is None or year_ago == 0:
        return None
    return round((curr - year_ago) / year_ago * 100, 2)


def _mom(curr: float, prev: float | None) -> float | None:
    if prev is None or prev == 0:
        return None
    return round((curr - prev) / prev * 100, 2)


def _to_float(s: Any) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def normalize(observations: list[dict]) -> list[dict]:
    """Convert BLS observations to clean dict, sorted newest-first, monthly only.
    Adds yoy_pct + mom_pct vs preceding observations in the same series.
    Skips observations whose value cannot be parsed (BLS sometimes returns '-').
    """
    monthly = []
    for o in observations:
        if not o["period"].startswith("M") or o["period"] == "M13":
            continue
        v = _to_float(o.get("value"))
        if v is None:
            continue
        monthly.append({**o, "_value": v})
    monthly.sort(key=lambda o: (int(o["year"]), _period_to_month(o["period"])), reverse=True)

    out = []
    for i, o in enumerate(monthly):
        val = o["_value"]
        prev = monthly[i + 1]["_value"] if i + 1 < len(monthly) else None
        year_ago = monthly[i + 12]["_value"] if i + 12 < len(monthly) else None
        out.append({
            "year": int(o["year"]),
            "month": _period_to_month(o["period"]),
            "period_name": o["periodName"],
            "value": val,
            "mom_pct": _mom(val, prev),
            "yoy_pct": _yoy(val, year_ago),
        })
    return out


# BLS Release schedule for CPI (offizielle Termine 2026, US Eastern Time 08:30).
# Wird ~jaehrlich gepflegt - BLS publiziert calendar fuer Vorjahr/aktuelles Jahr.
# Quelle: https://www.bls.gov/schedule/news_release/cpi.htm
CPI_RELEASE_SCHEDULE_2026 = [
    "2026-01-14",
    "2026-02-11",
    "2026-03-12",
    "2026-04-10",
    "2026-05-12",
    "2026-06-11",
    "2026-07-15",
    "2026-08-12",
    "2026-09-11",
    "2026-10-15",
    "2026-11-13",
    "2026-12-10",
]


def next_release_after(today: date) -> str | None:
    today_s = today.isoformat()
    for d in CPI_RELEASE_SCHEDULE_2026:
        if d >= today_s:
            return d
    return None
