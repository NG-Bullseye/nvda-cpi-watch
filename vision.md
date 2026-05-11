# Vision — nvda-cpi-watch Roadmap

Stand: 2026-05-11. Phase 1 ist live, Phase 2+ Skizze.

## Phase 1 — Passiv (jetzt)

On-demand MCP-Server + Repo-Agent. Tools liefern NVDA-Earnings + US-CPI Daten plus aggregierten Trade-Brief. Agent wird gespawnt, antwortet, endet.

**Status:** in build. Erster Use-Case: CPI-Print am 2026-05-12 14:30 MEZ — Trade-Brief fuer Long-Hebel-Setup auf Tech/NVDA.

## Konsens-Forecast Quellen-Erweiterung (Phase 1.5)

**Bekanntes Problem:** Finnhub `/calendar/economic` liefert fuer US-CPI nur Index-Werte (z.B. 330.21), keinen YoY-Konsens-Forecast (`estimate: null`). Damit fehlt im `cpi_trade_brief` der wichtigste Vergleichswert.

**Optionen fuer zweite Quelle:**
- **Trading Economics API** — free tier mit `guest:guest` key, liefert CPI YoY consensus.
- **ForexFactory Calendar** — JSON-Feed `https://www.forexfactory.com/calendar?week=this`, scraping; CPI YoY forecast aus "Forecast"-Spalte.
- **Investing.com Economic Calendar** — fragiles HTML-scraping, JS-loaded.
- **Manuelle Hardcode-Fallback** — `forecast_overrides.yaml` mit YoY-Konsens pro Release, manuell gepflegt.

Empfehlung: **Trading Economics als primary**, ForexFactory als fallback.

## Phase 2 — Watcher (persistent)

Agent laeuft als langlebige tmux-Session. Cron-getrieben prueft er taeglich auf bevorstehende Events:

- CPI-Release in <= N Tagen → Pre-Brief
- NVDA-Earnings in <= N Tagen → Pre-Brief

Output-Kanaele (Auswahl, zu entscheiden):
- Telegram-Bot (an Leos triage-Bot)
- Cortex-Event ueber Redis-Stream
- HA-Notification

Trigger fuer Event-Pings:
- T-3 Tage: erste Erinnerung + aktueller Forecast
- T-1 Tag: Nowcast-Update, Surprise-Potential
- T-2h: finale Lage-Einschaetzung
- T+5min (Post-Release): tatsaechlicher Print vs Forecast, Reaktion benennen

## Phase 3 — Analyst (post-event)

Nach jedem Release/Earnings:

- Tatsaechliche Werte ziehen, gegen Estimate + Nowcast vergleichen
- Surprise quantifizieren
- Kurz-Report (~150 Worte) schreiben: was kam, was hatte der Markt erwartet, wo war der Spread
- Optional: NVDA-Kursreaktion in den ersten 60min via Finnhub Quote-API

Output → `~/repos/nvda-cpi-watch/reports/YYYY-MM-DD.md` plus Telegram-Push.

## Phase 4 — Kombiniert

Watcher + Analyst in einer langlebigen Agent-Session. Self-healing-Pattern (siehe `~/.claude/CLAUDE.md` "Live-Self-Healing-Pattern"): strukturierte Logs, Live-Tail-faehig, Watchdog-MCP kann Anomalien (Forecast-Drift, Tool-Errors) detektieren.

Ggf. erweitern um:
- Weitere Tech-Tickers (AAPL, MSFT, GOOGL) konfigurierbar
- Weitere Makro-Releases (PCE, FOMC, NFP)
- Sentiment-Layer (News-Headlines vor Release)
- Historische Backtest-Helper: "wie hat NVDA in der Vergangenheit auf CPI-Surprise X reagiert?"

## Nicht-Ziele

- KEIN automatisches Trading. Niemand setzt Orders aus diesem Repo.
- KEIN finanzielles Trade-Advice. Werkzeug, keine Empfehlung.
- KEIN Web-Scraping ausser Cleveland Fed (offizielle APIs bevorzugt).
