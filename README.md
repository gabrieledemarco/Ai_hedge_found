# AI Hedge Fund — Paper Trading Quant Platform

Piattaforma di paper trading multi-strategia con capitale iniziale di **3.000 €** per strategia,
su 20 titoli di **NASDAQ**, **NYSE**, **FTSE** e **Borsa Italiana**. Gira su GitHub Actions
(nessun server), notifica su Telegram e pubblica una dashboard interattiva su GitHub Pages.
Nessun denaro reale è coinvolto.

## Strategie

Tutte implementano `BaseStrategy.compute_weights(universe, prices, signals) -> {ticker: peso}`.

| Strategia | Idea | Segnali usati | Live |
|---|---|---|:-:|
| `equal_weight` | 1/N su tutto l'universo | – | ✅ |
| `momentum` | top 10 per rendimento a 3 mesi | `momentum.return_3m` | ✅ |
| `fundamental` | pesi proporzionali all'F-score (P/E, ROE, FCF, D/E) | `fundamentals.f_score` | ✅ |
| `sentiment` | pesi da sentiment news (Alpha Vantage + FinBERT) | `sentiment.score` | ✅ |
| `trend_momentum` | momentum, ma solo sopra la media mobile a 200gg; altrimenti cassa | `momentum`, `trend` | solo backtest |
| `inverse_volatility` | peso ∝ 1/volatilità (risk-parity semplificato) | `volatility.vol_60d` | solo backtest |

`RiskManagedStrategy(strategia)` (in `strategies/risk.py`) è un livello che avvolge qualunque
strategia con un tetto per titolo (15%) e per settore (35%); l'eccesso va sui titoli con spazio e,
se non ce n'è, resta in cassa. Il backtest include `momentum_risk` per misurare se aiuta.

Le ultime due sono disponibili nel codice e nel backtest, ma non sono ancora registrate in
`STRATEGIES` (`scripts/config.py`): farlo crea un nuovo portafoglio live e va deciso consapevolmente.
Aggiungere una strategia = una classe in `scripts/strategies/` + export in `__init__.py`.

## Architettura

| File | Ruolo |
|---|---|
| `scripts/main_pipeline.py` | Orchestratore: prezzi, FX, ordini per strategia, report, dashboard |
| `scripts/fetch_prices.py` | Prezzi: Tiingo (US) → Alpha Vantage (EU) → yfinance, con cache giornaliera |
| `scripts/fetch_fundamentals.py`, `fetch_sentiment.py` | Calcolo segnali → `data/signals.json` |
| `scripts/fundamentals_sources.py` | Fonti dei fondamentali (Yahoo → Alpha Vantage), cache per titolo e rotazione della quota |
| `scripts/portfolio_io.py` | Lettura/scrittura dei portafogli JSON in `data/portfolios/` |
| `scripts/valuation.py` | Valutazione del portafoglio in EUR (un solo calcolo, prima e dopo gli ordini) |
| `scripts/fx.py` | Cambi verso EUR: Frankfurter (BCE) → Alpha Vantage, con cache giornaliera (`data/fx_cache.json`) e ultimo tasso noto |
| `scripts/metrics.py` | Metriche (Sharpe, Sortino, drawdown, CAGR, Calmar) e ricostruzione dell'equity storica |
| `scripts/price_history.py` | Storico prezzi: ricostruito dai log (segnali momentum/volatilità/trend) e persistito in `data/price_history.json` (prezzi, FX, benchmark) |
| `scripts/signals_utils.py`, `strategies/signal_utils.py` | Cosa conta come segnale reale; momentum dallo storico; merge non distruttivo dei fondamentali |
| `scripts/signal_health.py` | Copertura dei segnali e avviso nel report se troppo bassa |
| `scripts/market_note.py` | Nota di mercato nel report Telegram (vedi sotto) |
| `scripts/repair_history.py` | Ripara i valori storici falsati da prezzi mancanti (anteprima di default) |
| `scripts/backtest.py` | Backtest storico con benchmark |
| `scripts/dashboard_data.py`, `dashboard_generator.py`, `templates/dashboard.html` | Dashboard statica (`docs/index.html` + `docs/data.json`) |
| `scripts/backfill_history.py` | Backfill locale di prezzi, FX e benchmark in `data/price_history.json` |
| `web/` | Server Flask (dashboard live sulla porta 10000) e app Streamlit |

### Workflow

- `paper_trading.yml` — 3 sessioni al giorno nei giorni feriali; committa i JSON aggiornati e la dashboard.
- `market_analysis.yml` — ogni mattina aggiorna `data/signals.json` (fondamentali, momentum, sentiment).
- `backtest.yml` — manuale o mensile: rigenera `docs/backtest.{md,json,png}`.
- `ci.yml` — su ogni push/PR: `ruff` + `pytest` (Python 3.10 e 3.12).

### Regole di esecuzione ordini

1. Peso target dalla strategia → valore target in EUR.
2. **Filtro anti-costi**: nessun ordine se lo scostamento dal target è < 5% del portafoglio.
3. **Lotti interi**: acquisti/vendite arrotondati per difetto a un numero intero di azioni.
4. I prezzi USD/GBP/GBp sono convertiti in EUR con il cambio del giorno.
5. **Costi di transazione simulati** (commissione + slippage): `TRANSACTION_COST_BPS` in
   `scripts/config.py` (default 10 bps sul controvalore). Registrati in `fee_eur` per ogni
   transazione e in `metadata.fees_paid`; valgono solo per i nuovi trade.
6. Se il prezzo di un titolo non è disponibile (fallback), per quel titolo il trading è sospeso.

## Qualità dei dati

Su GitHub Actions Yahoo Finance blocca le richieste e Alpha Vantage ha 25 richieste/giorno. La
pipeline è costruita perché questo non produca dati finti:

- **Segnali mancanti ≠ segnali a zero.** Se un segnale non si può calcolare, il ticker viene
  omesso (non riempito con `0.0` o `0.5`). Le strategie ignorano i ticker senza dato e, se non
  resta nulla, usano esplicitamente una lista di ripiego. Un fetch fallito non cancella dati
  fondamentali reali già presenti.
- **Fondamentali con cache e fallback.** Yahoo resta la fonte primaria (in locale funziona anche per FTSE e
  Borsa Italiana). Quando non risponde (GitHub Actions) si ripiega su Alpha Vantage `OVERVIEW` (P/E e ROE:
  niente FCF né debito/equity, quindi lo score usa meno metriche), con un budget di richieste per esecuzione
  (`AV_FUNDAMENTALS_PER_RUN`, default 5) per non consumare la quota condivisa con prezzi e sentiment. Ogni voce
  ha `fetched_at`, `source` e `metrics_used`: i dati freschi (< 14 giorni) non si riscaricano, le richieste
  vanno prima ai titoli senza dato e poi ai più vecchi, e un fetch fallito non cancella un dato reale.
- **Momentum dallo storico del progetto.** Se yfinance non risponde, il momentum a 3 mesi si
  calcola da `prices_used` nei log dei portafogli (nessuna chiamata di rete, nessuna chiave).
  Servono 64 giorni di prezzi per titolo: chi ne ha meno resta fuori finché non li accumula.
- **Valutazione coerente.** Un titolo senza prezzo del giorno è valutato all'ultimo prezzo reale
  noto, poi al costo medio. Mai a zero.
- **Cambi affidabili.** Fonte primaria Frankfurter (tassi BCE, senza chiave né quota), poi Alpha
  Vantage; un solo fetch per valuta al giorno e, se tutto fallisce, l'ultimo tasso reale e non un
  valore fisso. I tassi usati sono registrati in ogni iterazione (`fx_rates`).
- **Quota Alpha Vantage.** I ticker senza articoli nell'ultimo controllo non vengono richiesti
  di nuovo per 7 giorni (se i titoli europei non sono coperti, si risparmiano ~10 richieste/giorno).
- **Pipeline leggera.** `paper_trading.yml` installa `requirements-pipeline.txt` (niente torch):
  FinBERT serve solo a `market_analysis.yml`.
- **Copertura segnali nel report.** Se un segnale copre meno del 50% dei ticker, il report
  Telegram lo dice.

### Valori storici falsati

Le valutazioni registrate prima di queste correzioni contengono buchi (posizioni valutate a 0 nei
giorni con prezzi mancanti) e oscillazioni dovute al cambio di ripiego (USD 0,92 contro ~0,89
reale). Ci sono due modi per gestirli:

- **Dashboard (non distruttivo).** `metrics.build_equity_series` ricostruisce l'equity di ogni
  voce con prezzi e cambi storici reali (`data/price_history.json`), senza toccare i JSON dei
  portafogli. La dashboard segnala quante rilevazioni sono state ricostruite.
- **Riparazione dei file (opzionale).**

```bash
python scripts/repair_history.py           # anteprima, non scrive nulla
python scripts/repair_history.py --apply   # riscrive data/portfolios/*.json
```

La riparazione dei file è esatta per i titoli in EUR e approssimata per USD/GBP (cambio di
ripiego): per i numeri più fedeli usa la ricostruzione della dashboard.

## Dashboard

`docs/index.html` è una pagina autosufficiente (dati incorporati, grafici Plotly da CDN): si apre
anche da file locale. Il linguaggio visivo (token a livelli, light di default e dark progettato a
parte, accento derivato con `color-mix()`) segue il design system di DemoGeneratorOfficial.

- **Topbar** in vetro con navigazione per sezioni e **switch tema sole ⇄ luna**, salvato in
  localStorage (`aihf.theme`) e applicato prima del primo paint; `?theme=dark` lo forza;
- **Panoramica**: strategia in testa con confronto sul benchmark, classifica per rendimento
  (strategie e benchmark) con sparkline e quattro indicatori chiave;
- **Andamento** interattivo: Base 100, valore in € o drawdown, intervallo 1M / 3M / Tutto, serie attivabili
  una per una e marcatori ▲▼ delle operazioni di acquisto e vendita sulle curve;
- **Nota di mercato** nella panoramica (la stessa del report Telegram, template deterministico);
- **Metriche**: rendimento (anche con dividendi stimati), volatilità, Sharpe, Sortino, max drawdown e % giorni
  positivi, con evidenziazione del migliore, più la mappa rischio/rendimento. Annualizzato e Calmar sono
  omessi di proposito: con pochi mesi di storico sarebbero fuorvianti;
- **Rispetto al benchmark** (MSCI World o S&P 500): beta, correlazione, tracking error, information ratio,
  cattura di rialzi e ribassi, alpha annualizzato (indicativo);
- **Portafoglio** per strategia: allocazione (torta 3D), esposizione per settore, P&L per
  posizione e posizioni ordinabili; **screener** filtrabile e **trade conclusi**;
- **Stato dei dati**: copertura dei segnali, fondamentali (fonte ed età), fonte e freschezza dei prezzi, cambi,
  benchmark, dividendi e rilevazioni ricostruite;
- **Effetti**: card con tilt 3D e riflesso, luci lampeggianti sulle curve (non sulle sparkline);
  disattivati con `prefers-reduced-motion` e su touch;
- benchmark: MSCI World in EUR (`SWDA.MI`) e S&P 500 (`SPY`), configurabili in `config.BENCHMARKS`.

### Come sono confrontati i benchmark

- I benchmark sono **total return** (prezzi aggiustati / ETF ad accumulazione) e **in EUR**: l'S&P 500 è
  convertito con i cambi storici (`FX:USD` in `data/price_history.json`).
- La simulazione accredita solo la variazione di prezzo, non i dividendi. La dashboard ne **stima** l'importo
  (stacchi da Yahoo, salvati come `DIV:<ticker>` in `data/price_history.json`, azioni in portafoglio alla data
  ex-dividend, al lordo delle tasse) e lo mostra a parte: la colonna "Con div.*" e il confronto col benchmark
  usano questa stima.
- Le metriche relative allineano i portafogli alle **chiusure del giorno di borsa precedente**: i prezzi di una
  sessione sono l'ultima chiusura disponibile, quindi il valore con data D riflette il giorno precedente.
  Senza questo allineamento la correlazione col benchmark risulta ~0,04 invece di ~0,45.

Le stesse informazioni sono in `docs/data.json`. Per pubblicarla: Settings → Pages → sorgente
`docs/`. In locale, `python -m flask --app web.app run --port 10000` serve la stessa dashboard con
i prezzi live (`/api/data` per il JSON, `/legacy` per la vecchia versione).

## Backtest

```bash
pip install -r requirements-dev.txt
python scripts/backtest.py --years 5          # scrive docs/backtest.{md,json,png}
```

Confronta le strategie con **SPY** e **FTSE MIB** (buy & hold), in EUR, con ribilanciamento
mensile e costi di transazione (default 10 bps sul turnover, come nel live).

Il report include anche la **stabilità per sottoperiodo** (metà iniziale vs metà finale del
periodo): non è un walk-forward, perché le strategie hanno parametri fissi, ma mostra se un
risultato regge in entrambi i periodi o dipende da uno solo.

Limiti dichiarati:

- Sono testate solo le strategie con segnali ricostruibili dai prezzi *point-in-time*
  (`equal_weight`, `momentum`, `trend_momentum`, `inverse_volatility`). `fundamental` e `sentiment`
  non hanno uno storico gratuito affidabile: includerle darebbe look-ahead bias.
- Azioni frazionarie (il live usa lotti interi), cassa a rendimento zero, nessuna imposta.
- Il paniere è quello attuale (survivorship bias).

I risultati dell'ultima esecuzione sono in [`docs/backtest.md`](docs/backtest.md), se già generati.

## Nota di mercato su Telegram

Il report include una breve nota con migliore/peggiore strategia, operazioni del giorno,
sentiment e momentum più forti. **Di default è un template deterministico: nessuna AI, nessuna API
key, nessun costo.**

Opzionale: farla riscrivere da un LLM con un endpoint compatibile OpenAI (anche locale, es. Ollama).
Si attiva solo se sono impostate `LLM_BASE_URL` e `LLM_MODEL` (`LLM_API_KEY` solo se serve).
Se l'LLM non risponde, si torna al template.

## Setup

### Secret GitHub

| Secret | Uso | Obbligatorio |
|---|---|:-:|
| `TIINGO_API_KEY` | prezzi US e benchmark (free tier) | consigliato |
| `ALPHA_VANTAGE_KEY` | prezzi EU, news sentiment, FX di riserva (free tier) | consigliato |
| `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | notifiche | no |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | nota riscritta da LLM | no |

### Esecuzione locale

```bash
pip install -r requirements.txt        # include torch/transformers per FinBERT
export TIINGO_API_KEY=... ALPHA_VANTAGE_KEY=... TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=...
python scripts/main_pipeline.py --hour 7     # 7 = mattina, 15 = pomeriggio, 21 = sera

# Backfill di prezzi, FX, benchmark e dividendi in data/price_history.json (richiede Yahoo Finance)
python scripts/backfill_history.py --start 2026-06-01

# Fondamentali e momentum in data/signals.json (in locale Yahoo risponde; --force riscarica anche i dati freschi)
python scripts/fetch_fundamentals.py
```

### Sviluppo

```bash
pip install -r requirements-dev.txt    # leggero: niente torch
ruff check scripts tests
pytest
```

I test coprono pesi delle strategie, metriche ed equity ricostruita, valutazione, cambi, motore di
backtest (incluso l'assenza di look-ahead nei segnali), regole di esecuzione e costi degli ordini,
nota di mercato e struttura della dashboard.

## Universo

NASDAQ: AAPL, MSFT, GOOGL, AMZN, TSLA, NVDA · NYSE: JPM, JNJ, V, KO ·
FTSE: ULVR.L, HSBA.L, BP.L, GSK.L, RIO.L · BIT: ENI.MI, ISP.MI, ENEL.MI, LDO.MI, MONC.MI

Si modifica in `scripts/config.py` (`UNIVERSE`).

## Manutenzione

- **Reset di una strategia**: elimina `data/portfolios/<strategia>.json` (riparte da 3.000 €).
  Lo storico di `data/price_history.json` si mantiene.
- **Parametri**: `scripts/config.py` (`TRANSACTION_COST_BPS`, `RISK_FREE_RATE`, `BENCHMARKS`).
- **Fondamentali**: da GitHub Actions si aggiornano con la rotazione Alpha Vantage (pochi titoli al giorno, solo
  P/E e ROE); un `python scripts/fetch_fundamentals.py` periodico in locale li porta a 4 metriche con Yahoo
  e il dato reale non viene mai sovrascritto da un fetch fallito.
- **Dividendi**: `python scripts/backfill_history.py` aggiunge i nuovi stacchi (solo in locale: Yahoo è bloccato da Actions).
- **Orari**: cron in `.github/workflows/paper_trading.yml` (UTC, non seguono l'ora legale).
