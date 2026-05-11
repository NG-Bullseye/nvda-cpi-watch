"""Cleveland Fed Inflation Nowcasting scraper.
Source: https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting

Page hat zwei Tables, identifiziert ueber <caption>:
  - "Inflation, month-over-month percent change"
  - "Inflation, year-over-year percent change"
Beide Tables: Month | CPI | Core CPI | PCE | Core PCE | Updated.

Wir extrahieren die Zeile fuer den naechsten anstehenden Monat (= jueteste
Zeile = letzte Datenzeile, weil Cleveland-Fed-Modell prognostiziert
'present + next'). Fragil bei Page-Redesign.
"""
from __future__ import annotations

import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

URL = "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"
NUM_RE = re.compile(r"-?\d+\.\d+")


async def fetch_nowcast() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        r = await client.get(URL, headers={"User-Agent": "Mozilla/5.0 nvda-cpi-watch/0.1"})
        r.raise_for_status()
        html = r.text

    soup = BeautifulSoup(html, "lxml")

    result: dict[str, Any] = {
        "headline": {"mom_pct": None, "yoy_pct": None, "month": None, "updated": None},
        "core": {"mom_pct": None, "yoy_pct": None, "month": None, "updated": None},
        "source_url": URL,
        "warning": None,
    }

    for tbl in soup.find_all("table"):
        cap = tbl.find("caption")
        if not cap:
            continue
        caption = cap.get_text(" ", strip=True).lower()
        is_mom = "month-over-month" in caption
        is_yoy = "year-over-year" in caption
        if not (is_mom or is_yoy):
            continue

        rows = tbl.find("tbody").find_all("tr") if tbl.find("tbody") else tbl.find_all("tr")[1:]
        # We want the LAST row (most recent nowcast month)
        if not rows:
            continue
        last = rows[-1]
        cells = [c.get_text(" ", strip=True) for c in last.find_all(["td", "th"])]
        if len(cells) < 3:
            continue

        # Cols: Month | CPI | Core CPI | PCE | Core PCE | Updated
        month_label = cells[0]
        try:
            cpi = float(cells[1]) if NUM_RE.fullmatch(cells[1].replace("+", "")) or NUM_RE.search(cells[1]) else None
            core = float(cells[2]) if NUM_RE.search(cells[2]) else None
        except ValueError:
            cpi = core = None
        updated = cells[-1] if len(cells) >= 6 else None

        if is_mom:
            result["headline"]["mom_pct"] = cpi
            result["core"]["mom_pct"] = core
            result["headline"]["month"] = month_label
            result["core"]["month"] = month_label
            if updated:
                result["headline"]["updated"] = updated
                result["core"]["updated"] = updated
        elif is_yoy:
            result["headline"]["yoy_pct"] = cpi
            result["core"]["yoy_pct"] = core
            # month + updated already set by mom-table or set here
            if not result["headline"]["month"]:
                result["headline"]["month"] = month_label
                result["core"]["month"] = month_label
            if updated and not result["headline"]["updated"]:
                result["headline"]["updated"] = updated
                result["core"]["updated"] = updated

    if all(v is None for v in (
        result["headline"]["mom_pct"], result["headline"]["yoy_pct"],
        result["core"]["mom_pct"], result["core"]["yoy_pct"],
    )):
        result["warning"] = "no nowcast values extracted - page structure may have changed"

    return result
