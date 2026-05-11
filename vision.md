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

## Phase 5 — Daytrading-Stack (Scope-Erweiterung 2026-05-11)

Leos Vision (Originalzitat): "am ende wollen wir dass der mcp alles liefert was wir zum daytraden und earnings prediction etc brauchen".

Daraus abgeleitet — Tools die ein Daytrader / Earnings-Trader an einem typischen Morgen braucht:

### 5a. Pre-Market & Intraday Levels
- `quote_now(symbol)` — letzter Trade, Pre-Market-Move, Tages-Open/High/Low (Finnhub `/quote`)
- `levels(symbol)` — Pre-Market-High/Low, Open-Range (z.B. ersten 5/15min), ADR/ATR (14d), Vor-Tages-Close
- `relative_strength(symbol)` — Performance vs SPY/QQQ heute, RS-Score
- `volume_profile(symbol)` — Volume-relativ-zu-Avg, aussergewoehnlich aktive Strikes (Options-Flow falls Free-Source)

### 5b. Makro-Stack
- `market_calendar_today` — alle US-relevanten Releases heute (CPI, NFP, PCE, FOMC, Powell speeches) - TradingView Calendar reicht
- `vix_now` — aktueller VIX, intraday move
- `dxy_now` — Dollar-Index
- `yields(maturity=10y)` — Treasury Yields, Move vs gestern

### 5c. Earnings-Prediction-Layer
- `earnings_today_amc` / `earnings_today_bmo` — wer heute reportet
- `earnings_history_pattern(symbol)` — Beat-Rate, durchschnittliche Surprise %, durchschnittlicher post-print Move (1d, 5d)
- `earnings_implied_move(symbol)` — IV-implizierter erwarteter Move bis nach Earnings (aus ATM-Straddle, Finnhub Options falls Free)
- `earnings_estimate_drift(symbol)` — sind die Schaetzungen die letzten 30/60/90 Tage nach oben oder unten revidiert worden (= sell-side sentiment trend)
- `earnings_whisper(symbol)` — wenn Quelle gefunden: Whisper-Estimate vs Sell-Side-Consensus (typisch Estimize-style)

### 5d. NVDA-spezifisch (weil Hauptkandidat in Leos Trades)
- `nvda_chip_cycle_context` — wo sind wir im Cycle? AI-CapEx-Datenpunkte aus Hyperscaler-Earnings, Datacenter-Revenue-Trends
- `nvda_competitor_signals` — AMD/Broadcom Earnings/Guidance als leading indicator
- `nvda_options_skew` — Call/Put-Skew, unusual flow (falls Free-Source — sonst Phase 5e)

### 5e. Sentiment / News
- `news_today(symbol)` — Finnhub `/news` oder NewsAPI
- `social_sentiment(symbol)` — Reddit/X-mention-velocity (out-of-scope solange Daten-Quelle nicht klar)

### Architektur-Anpassung fuer Phase 5

- Datenquellen-Layer waechst: TradingView, Finnhub, BLS, FRED (neu fuer Yields/DXY/VIX-Historie), Cleveland Fed.
- Tools-Anzahl waechst von 9 (Phase 1) auf ~25-30.
- Caching wird wichtiger — Intraday-Daten (Quote, VIX) brauchen TTL <30s; statische Earnings-Pattern 1d.
- Trade-Brief wird zu einem **`daytrading_brief(date=today)`** das alles aggregiert: heutige Releases + relevante Symbole + Levels + Risk-Off-Signale.

### Phasing innerhalb Phase 5

1. **5a + 5b zuerst** (Quote/Levels + Makro-Stack) — Basis fuer jeden Trading-Tag
2. **5c danach** (Earnings-Layer) — Pre-Earnings ist haeufiger Trade-Anlass als CPI
3. **5d/5e zuletzt** — spezialisiert, optional

Komplettes Bauen erst nach: Phase 2 (Watcher) + Phase 3 (Analyst). Daytrading-Stack ohne Watcher waere unvollstaendig — Live-Daten brauchen Live-Refresh.

## Nicht-Ziele

- KEIN automatisches Trading. Niemand setzt Orders aus diesem Repo.
- KEIN finanzielles Trade-Advice. Werkzeug, keine Empfehlung.
- KEIN Web-Scraping ausser Cleveland Fed (offizielle / public APIs bevorzugt).
- KEIN Brokerage-Integration (keine Trade-Republic-API-Calls etc.) - reine Daten-Schicht.
