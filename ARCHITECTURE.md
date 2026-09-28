# ARCHITECTURE — nvda-cpi-watch

## Deep Modules — CPI- und NVDA-Daten als MCP-Tools (Phase 1, passiv)

Flow: ein Tool-Call über stdio landet in `server.py::call_tool`, der Handler holt Daten über einen Quell-Client, jeder Abruf läuft durch den File-Cache mit TTL. Die Sequenz lebt in `server.py::call_tool`. Jede Innenleben-Zelle ist datei:zeile und muss per grep -n treffen.

## Flow

**Sequenz**

| # | Modul | Eingang | Ausgang | Bedingung | Stellschraube | Innenleben |
|---|---|---|---|---|---|---|
| 1 | MCP | Tool-Call (stdio) | TextContent (JSON) | — | `TOOLS` (9 Tools) | server.py:574 `async def call_tool` |
| 2 | Cache | Key, TTL, fetcher | Daten aus `cache/*.json` oder frisch | TTL abgelaufen | TTL je Tool | cache.py:36 `async def cached` |
| 3 | BLS | Series-IDs | CPI Headline/Core | — | `BLS_API_KEY` optional | bls.py:25 `async def fetch_series` |
| 4 | Konsens | Release-Datum | Median aus drei Quellen | — | — | server.py:287 `async def _cpi_consensus` |
| 5 | Trade-Brief | Konsens + Nowcast + BLS | Aggregat mit `_derivation` | — | — | server.py:398 `async def _cpi_trade_brief` |

**Parallel**

| Modul | Eingang | Ausgang | Bedingung | Stellschraube | Innenleben |
|---|---|---|---|---|---|
| Finnhub | Symbol, Zeitraum | Earnings, Economic Calendar | `FINNHUB_API_KEY` | — | finnhub.py:24 `async def _get` |
| Cleveland Fed | HTML | Nowcast | Scrape fragil | — | clevelandfed.py:25 `async def fetch_nowcast` |
| TradingView | Zeitraum | CPI-Konsens | — | — | tradingview.py:89 `async def fetch_us_cpi_for_release` |
| ForexFactory | Wochen-Feed | CPI-Konsens | — | — | forexfactory.py:25 `async def fetch_us_cpi_for_release` |
| Investing.com | Event-Seite | CPI-Konsens | — | — | investing.py:102 `async def fetch_us_cpi_for_release` |

## Schnittstellen

- MCP stdio, Registrierung per `.mcp.json`.
- Release-Termine hart codiert (bls.py:110 `CPI_RELEASE_SCHEDULE_2026`).
- Cache `cache/*.json` gitignored.

## Standard: Deep Modules + Flow

Standard R1–R5 steht in `~/repos/speech-engine/ARCHITECTURE.md`.
