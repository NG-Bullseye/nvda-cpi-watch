# STATUS

Stand: 2026-05-11

## Phase 1 — Passiv MCP

| Komponente | Status |
|---|---|
| Repo-Skeleton + venv + deps | done |
| `bls.py` (Headline + Core, Schedule) | done |
| `finnhub.py` (Earnings + Economic Calendar) | done |
| `clevelandfed.py` (Nowcast scrape) | done, fragil |
| `cache.py` (File-TTL) | done |
| `server.py` (8 Tools, stdio) | done |
| `.mcp.json` + `.env.example` | done |
| CLAUDE.md + README + vision | done |
| Smoke-Test BLS live | done |
| Smoke-Test Finnhub | done (Key in `~/.bashrc`) |
| Smoke-Test Nowcast live | done |
| Initial commit | done (f0f9e15) |

## Key-Setup

`FINNHUB_API_KEY` ist in `~/.bashrc` exportiert (analog zu `ESPHOME_API_KEY`). Wird vererbt an `claude`-Prozesse die aus interaktiver Shell starten. `python-dotenv` liest zusaetzlich `.env` falls vorhanden - env wins.

## Bekannte Limitierungen

- **Finnhub `/calendar/economic` liefert fuer US-CPI nur Index-Werte (z.B. 330.21), keinen YoY-Konsens-Forecast.** `estimate`-Feld ist `null`. Bedeutet: Trade-Brief hat kein automatisches Konsens-YoY → manuell setzen oder zweite Quelle (Phase 2: Trading Economics / ForexFactory).
- **Cleveland-Fed-Scraper fragil**: Page-Redesign bricht das Tool. Aktuell funktioniert es; bei Bedarf gegen aktuelles HTML neu anpassen.
- **BLS Release Schedule hardcoded** fuer 2026 in `bls.py` → zum Jahresende aktualisieren.

## Naechste Schritte

- Agent-Spawn testen: `tmux new-session -d -s nvda-cpi-watch "cd ~/repos/nvda-cpi-watch && claude --mcp-config .mcp.json"`
- Phase-2 Vorbereitung: zweite Quelle fuer YoY-Konsens-Forecast (siehe `vision.md`)
- NVDA Earnings 2026-05-20 AMC: Pre-Brief kurz vor Release ziehen

## Risiken

- **Cleveland-Fed-Scraper fragil**: Page-Redesign bricht das Tool. Fallback liefert `raw_snippet` zur manuellen Inspektion plus Warning-Field. Bei Bedarf gegen aktuelles HTML neu parametrisieren.
- **BLS Release Schedule hardcoded** fuer 2026. Zum Jahresende aktualisieren (`bls.py` → `CPI_RELEASE_SCHEDULE_2026`).
- **Finnhub Free Tier**: 60 calls/min — easy reach, aber Earnings-Calendar zaehlt evtl. pro Symbol. Caching haelt das in Schach.

## Naechste Schritte

- Smoke-Tests (BLS + Nowcast live)
- Erste committed Version
- Nach Finnhub-Key: scharfschaltung + Trade-Brief Demo-Run
