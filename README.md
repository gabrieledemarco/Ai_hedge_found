# Paper Trading Quant Platform

Piattaforma di Paper Trading multi-mercato con capitale iniziale **3.000 €**, esposta su **NASDAQ**, **NYSE**, **FTSE** e **Borsa Italiana (BIT)**. Integrata con GitHub Actions per esecuzione schedulata e Telegram per notifiche.

---

## Architettura

### Componenti

| Componente | Ruolo |
|---|---|
| `scripts/main_pipeline.py` | Orchestratore principale: prezzo, FX, allocazione, esecuzione |
| `scripts/portfolio_io.py` | I/O sul file JSON del portafoglio |
| `scripts/telegram_utils.py` | Notifiche Telegram via HTTP POST (HTML parse mode) |
| `data/portfolio_history.json` | Archivio persistente del portafoglio (versionato su Git) |
| `.github/workflows/paper_trading.yml` | CI/CD: 3 sessioni giornaliere + auto-commit |

### Flusso di esecuzione

1. GitHub Actions attiva il workflow al trigger `schedule` (3 volte al giorno)
2. Si determina l'ora locale italiana via `TZ=Europe/Rome`
3. La pipeline carica lo stato corrente del portafoglio da `portfolio_history.json`
4. Recupera i prezzi via **Tiingo API** e i tassi FX via **Alpha Vantage API**
5. Calcola l'allocazione target (equal-weight su 15 ticker)
6. Applica il **filtro anti-costi del 5%**
7. Esegue ordini BUY/SELL a lotti interi (no frazioni)
8. Salva lo storico e invia notifica Telegram
9. Git committa e pusha automaticamente il JSON aggiornato

---

## Sessioni di trading

| Sessione | Ora IT (winter) | Ora IT (summer) | Descrizione |
|---|---|---|---|
| **Mattina** | 08:15 | 09:15 | Apertura mercati EU, pre-apertura US |
| **Pomeriggio** | 17:15 | 18:15 | Trading intraday US |
| **Sera** | 22:30 | 23:30 | Chiusura US, report di fine giornata |

Le notifiche Telegram:

- **Sera**: report completo sempre inviato
- **Mattina / Pomeriggio**: notifica SOLO se ci sono state transazioni reali (BUY/SELL)

---

## Gestione del rischio

### Filtro anti-costi (5%)

Nessuna operazione viene eseguita se lo scostamento tra peso target e peso reale è inferiore al **5%**. Questo previene il _whipsaw_ da micro-ribilanciamenti che genererebbero costi di transazione fittizi.

### Arrotondamento a lotti interi

Tutti gli ordini BUY/SELL sono arrotondati per difetto al numero intero di azioni. Nessuna frazione di azione viene mai acquistata o venduta.

### Conversione valute

I prezzi in USD e GBP vengono convertiti in EUR tramite tassi FX live (Alpha Vantage) prima di ogni calcolo di portafoglio.

---

## Setup

### 1. Prerequisiti

- Python 3.10+
- Repository GitHub privato
- API key per:
  - [Tiingo](https://www.tiingo.com/) (prezzi azionari)
  - [Alpha Vantage](https://www.alphavantage.co/) (tassi di cambio)
  - [Telegram Bot](https://core.telegram.org/bots#6-botfather) (notifiche)

### 2. GitHub Secrets

Imposta i seguenti segreti nella repository GitHub:

| Secret | Descrizione |
|---|---|
| `TIINGO_API_KEY` | API key per Tiingo |
| `ALPHA_VANTAGE_KEY` | API key per Alpha Vantage |
| `TELEGRAM_TOKEN` | Token del bot Telegram (da @BotFather) |
| `TELEGRAM_CHAT_ID` | Chat ID dove ricevere le notifiche |

### 3. Esecuzione locale

```bash
# Clona la repo
git clone <repo-url>
cd paper-trading-quant

# Imposta variabili d'ambiente
export TIINGO_API_KEY=your_key
export ALPHA_VANTAGE_KEY=your_key
export TELEGRAM_TOKEN=your_token
export TELEGRAM_CHAT_ID=your_chat_id

# Installa dipendenze
pip install pandas requests yfinance

# Esegui una sessione
python scripts/main_pipeline.py --hour 7    # mattina
python scripts/main_pipeline.py --hour 15   # pomeriggio
python scripts/main_pipeline.py --hour 21   # sera
```

### 4. Attivazione su GitHub Actions

Dopo aver pushato la repository su GitHub, assicurati che **Actions** sia abilitato. Il workflow si attiverà automaticamente agli orari schedulati (UTC) dal lunedì al venerdì.

### 5. Dashboard interattiva

Ad ogni iterazione viene generata una **dashboard HTML professionale** in `docs/index.html` con:

- **Metriche istituzionali**: Sharpe ratio, Max Drawdown, Calmar Ratio, Win Rate, Profit Factor
- **Equity Curve** interattiva (Plotly) con overlay della cassa
- **Asset Allocation** treemap
- **Sector Exposure** a barre
- **Drawdown chart**
- **Distribuzione dei rendimenti giornalieri**
- **PnL per singolo asset**
- **Tabella posizioni** con PnL assoluto e percentuale
- **Storico transazioni**

Per visualizzarla:
- **GitHub Pages**: vai su Settings → Pages → sorgente `docs/` → salva. Poi visita `https://<user>.github.io/<repo>/`
- **Locale**: apri `docs/index.html` nel browser

---

## Universo dei ticker

### NASDAQ
AAPL, MSFT, GOOGL, AMZN, TSLA, NVDA

### NYSE
JPM, JNJ, V, KO

### FTSE (London)
ULVR.L, HSBA.L, BP.L, GSK.L, RIO.L

### Borsa Italiana (BIT)
ENI.MI, ISP.MI, ENEL.MI, LDO.MI, MONC.MI

---

## Manutenzione

- **Reset del portafoglio**: sostituisci `data/portfolio_history.json` con il contenuto iniziale
- **Modifica ticker**: aggiorna `UNIVERSE` in `scripts/main_pipeline.py`
- **Cambio orari**: modifica i cron expressions in `.github/workflows/paper_trading.yml`
