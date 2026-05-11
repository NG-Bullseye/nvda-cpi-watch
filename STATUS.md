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
| Smoke-Test BLS live | pending |
| Smoke-Test Finnhub (Key noetig) | blocked auf Key |
| Smoke-Test Nowcast live | pending |
| Initial commit | pending |

## Offene Punkte fuer Leo

1. **Finnhub-Key** anlegen → `~/repos/nvda-cpi-watch/.env`. Ohne: Forecast + Earnings liefern `{"error": "FINNHUB_API_KEY not set"}`.
2. **Optional** BLS-Key fuer hoehere Rate-Limits.
3. **Agent-Spawn testen** sobald Key da: `tmux new-session -d -s nvda-cpi-watch "cd ~/repos/nvda-cpi-watch && claude --mcp-config .mcp.json"`.

## Risiken

- **Cleveland-Fed-Scraper fragil**: Page-Redesign bricht das Tool. Fallback liefert `raw_snippet` zur manuellen Inspektion plus Warning-Field. Bei Bedarf gegen aktuelles HTML neu parametrisieren.
- **BLS Release Schedule hardcoded** fuer 2026. Zum Jahresende aktualisieren (`bls.py` → `CPI_RELEASE_SCHEDULE_2026`).
- **Finnhub Free Tier**: 60 calls/min — easy reach, aber Earnings-Calendar zaehlt evtl. pro Symbol. Caching haelt das in Schach.

## Naechste Schritte

- Smoke-Tests (BLS + Nowcast live)
- Erste committed Version
- Nach Finnhub-Key: scharfschaltung + Trade-Brief Demo-Run
