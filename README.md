# nvda-cpi-watch

MCP-Server + Repo-Agent fuer NVDA-Earnings + US-CPI Daten. Liefert historische Werte, Markt-Forecasts (Finnhub), Live-Nowcasts (Cleveland Fed), und einen aggregierten Trade-Brief fuer den naechsten CPI-Release.

## Quickstart

```bash
cd ~/repos/nvda-cpi-watch
cp .env.example .env
# Edit .env: FINNHUB_API_KEY=... (free key from https://finnhub.io/register)

# Dependencies sind im venv installiert. Falls nicht:
python3 -m venv venv && venv/bin/pip install -r requirements.txt

# Agent spawnen (Repo-MCP wird automatisch geladen via .mcp.json):
tmux new-session -d -s nvda-cpi-watch "cd ~/repos/nvda-cpi-watch && claude --mcp-config .mcp.json"
tmux attach -t nvda-cpi-watch
```

Alternativ Standalone-Server testen:

```bash
venv/bin/python server.py < /dev/null   # startet stdio-loop, EOF beendet
```

## Tools

| Tool | Zweck | Quelle |
|---|---|---|
| `cpi_latest` | Letzter Headline + Core CPI, MoM/YoY | BLS API v2 |
| `cpi_history(months=N)` | Reihe der letzten N Monate | BLS API v2 |
| `cpi_next_release` | Naechster Release-Termin | BLS Schedule (hardcoded) |
| `cpi_forecast` | Markt-Konsens fuer naechsten Release | Finnhub |
| `cpi_nowcast` | Cleveland Fed Live-Modell | clevelandfed.org (HTML-scrape) |
| `cpi_trade_brief` | Aggregat: Forecast/Nowcast/Previous + Surprise | alle drei |
| `nvda_earnings_history(quarters=N)` | Letzte N Quartale | Finnhub |
| `nvda_earnings_next` | Naechster Earnings-Termin | Finnhub |

## Env

| Var | Notwendig | Quelle |
|---|---|---|
| `FINNHUB_API_KEY` | Ja, fuer Forecast + Earnings | https://finnhub.io/register |
| `BLS_API_KEY` | Nein (optional, hoehere Limits) | https://data.bls.gov/registrationEngine/ |

## Architektur

```
server.py            ← MCP stdio, Tool-Registry, Dispatch
├── bls.py           ← BLS API client + CPI Release Schedule
├── finnhub.py       ← Finnhub client (Earnings + Economic Calendar)
├── clevelandfed.py  ← HTML scraper fuer Inflation Nowcasting
└── cache.py         ← File-Cache (TTL je Tool)
```

Cache-Files unter `cache/*.json` (gitignored). TTLs: BLS 6h, Finnhub Earnings 1h, Forecast 30min, Nowcast 3h.

## Phase 1 = passiv

Aktuelle Phase: on-demand Daten-Server. Keine Alerts, keine Cron-Jobs, keine HA-Integration. Roadmap → `vision.md`.

## Disclaimer

Daten-Server, keine Anlage- oder Trade-Beratung. Werte direkt aus BLS / Finnhub / Cleveland Fed; bei Drift Source pruefen.
