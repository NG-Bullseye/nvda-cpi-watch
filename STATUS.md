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

## Konsens-Layer (2026-05-11 hinzu)

- **TradingView Calendar API** als primary (`tradingview.py`, kein Key, kein Quota)
- **ForexFactory feed** als fallback (`forexfactory.py`)
- **`cpi_consensus` Tool** liefert Headline YoY/MoM + Core MoM direkt
- **Core YoY derivation** in `_cpi_consensus()`: (latest_core_idx * (1 + mom/100)) / year_ago_core_idx - 1
- **`cpi_trade_brief`** befuellt jetzt forecast-Felder automatisch (vorher: null)

## SA/NSA-Refactor (2026-05-11 nachmittag)

- **Bug:** BLS-Client zog nur NSA (`CUUR*`); TradingView-Consensus + Cleveland-Fed-MoM sind SA-basis → unit-mismatch beim Vergleich. Verifiziert: SA-Serie liefert exakt die "previous"-Werte die TradingView zeigt (0.2% Core MoM, 0.9% Headline MoM für März).
- **Fix in `bls.py`:** zusaetzliche Konstanten `SERIES_HEADLINE_SA`, `SERIES_CORE_SA` (CUSR-prefix).
- **`cpi_latest`** liefert jetzt beide Bases: `headline.nsa / headline.sa / core.nsa / core.sa`. Convention: MoM-Headline = SA, YoY-official-press-release = NSA.
- **`cpi_consensus` Core-YoY-Derivation** auf reine SA-Basis: SA-MoM-Forecast wird auf SA-year-ago-Index angewendet. Feld umbenannt: `core_yoy_derived_pct` → `core_yoy_derived_pct_sa`. NSA-YoY-Derivation entfaellt (kein public NSA-MoM-Consensus existiert).
- **`cpi_trade_brief`** umstrukturiert auf MoM-first:
  - `primary_signal_core_mom` (SA, unit-clean ueber BLS/TV/CL-Fed)
  - `secondary_signal_headline_mom` (SA)
  - `context_core_yoy` mit getrennten `sa_basis`- und `nsa_basis`-Bloecken (keine Mixing-Artefakte mehr)
  - `context_headline_yoy` zeigt previous auf beiden Bases plus Forecast (SA) und Nowcast (NSA)
- **Cache invalidiert** fuer `bls_latest`; alter 2-Series-Shape würde leere SA-Felder ergeben.

## Bekannte Limitierungen

- **Core CPI YoY Konsens**: keine Free-API publiziert das direkt → wir derivieren mathematisch aus Core MoM Forecast + BLS Vorjahresindex. Exakt sobald MoM-Konsens steht. Source-Transparenz im `_derivation`-Feld.
- **Cleveland-Fed-Scraper fragil**: Page-Redesign bricht das Tool. Aktuell funktioniert es; bei Bedarf gegen aktuelles HTML neu anpassen.
- **BLS Release Schedule hardcoded** fuer 2026 in `bls.py` → zum Jahresende aktualisieren.
- **Finnhub Free** liefert fuer CPI nur Index-Level (`cpi_forecast` Tool DEPRECATED, durch `cpi_consensus` ersetzt).

## Naechste Schritte

- Agent-Spawn testen: `tmux new-session -d -s nvda-cpi-watch "cd ~/repos/nvda-cpi-watch && claude --mcp-config .mcp.json"`
- Phase 5: Daytrading-Stack (siehe `vision.md` - Quote/Levels/IV/Earnings-Patterns)
- NVDA Earnings 2026-05-20 AMC: Pre-Brief kurz vor Release ziehen

## Risiken

- **Cleveland-Fed-Scraper fragil**: Page-Redesign bricht das Tool. Fallback liefert `raw_snippet` zur manuellen Inspektion plus Warning-Field. Bei Bedarf gegen aktuelles HTML neu parametrisieren.
- **BLS Release Schedule hardcoded** fuer 2026. Zum Jahresende aktualisieren (`bls.py` → `CPI_RELEASE_SCHEDULE_2026`).
- **Finnhub Free Tier**: 60 calls/min — easy reach, aber Earnings-Calendar zaehlt evtl. pro Symbol. Caching haelt das in Schach.

## Naechste Schritte

- Smoke-Tests (BLS + Nowcast live)
- Erste committed Version
- Nach Finnhub-Key: scharfschaltung + Trade-Brief Demo-Run
