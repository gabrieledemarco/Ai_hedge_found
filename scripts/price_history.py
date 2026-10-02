"""Storico prezzi: (1) ricostruito dai log delle iterazioni + segnali derivati,
(2) serie giornaliera persistita in data/price_history.json (prezzi, FX, benchmark).

Parte 1 - ricostruzione dai log + segnali derivati.

Perche' esiste: su GitHub Actions Yahoo Finance blocca le richieste, quindi i
segnali calcolati con yfinance (momentum, fondamentali) restano vuoti. I prezzi
reali pero' ci sono: ogni sessione li scrive in `iterations_log[*].prices_used`.
Da li' si ricostruisce una serie giornaliera, senza chiamate di rete, senza
nuove chiavi API e senza nuovi file da versionare.

I prezzi sono in valuta locale: i rendimenti ignorano quindi la componente FX.
"""
import glob
import json
import math
import os
from datetime import date

PORTFOLIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "portfolios")

TRADING_DAYS = 252
MOMENTUM_3M = 63
MOMENTUM_1M = 21
VOL_WINDOW = 60
TREND_WINDOW = 200
MIN_OBS = 10  # sotto questa soglia nessun segnale: meglio nessun dato che dati finti

# Valori usati dalla pipeline come prezzo "nominale" quando il fetch fallisce
_PLACEHOLDERS = {100.0, 150.0}


def _is_placeholder_day(prices: dict) -> bool:
    vals = [v for v in prices.values() if v and v > 0]
    if not vals:
        return True
    return sum(1 for v in vals if v in _PLACEHOLDERS) / len(vals) >= 0.5


def load_history(portfolios_dir: str = PORTFOLIOS_DIR) -> dict[str, list[tuple[str, float]]]:
    """{ticker: [(YYYY-MM-DD, prezzo), ...]} ordinato, un valore per giorno
    (l'ultimo registrato). Scarta i giorni con prezzi nominali di fallback."""
    per_day: dict[str, dict[str, tuple[str, float]]] = {}
    for path in sorted(glob.glob(os.path.join(portfolios_dir, "*.json"))):
        try:
            with open(path) as f:
                log = json.load(f).get("iterations_log", [])
        except (OSError, json.JSONDecodeError):
            continue
        for entry in log:
            prices = entry.get("prices_used") or {}
            ts = entry.get("timestamp", "")
            if not ts or _is_placeholder_day(prices):
                continue
            day = ts[:10]
            for ticker, price in prices.items():
                if not price or price <= 0:
                    continue
                cur = per_day.setdefault(ticker, {}).get(day)
                if cur is None or ts >= cur[0]:
                    per_day[ticker][day] = (ts, float(price))
    return {
        t: sorted((d, v[1]) for d, v in days.items()) for t, days in per_day.items()
    }


def latest_prices(history: dict[str, list[tuple[str, float]]]) -> dict[str, float]:
    """Ultimo prezzo reale noto (valuta locale) per ticker."""
    return {t: series[-1][1] for t, series in history.items() if series}


def compute_price_signals(history: dict[str, list[tuple[str, float]]]) -> dict:
    """Segnali dai soli prezzi. Un ticker senza abbastanza storico viene OMESSO
    dal segnale (mai riempito con 0.0), cosi' le strategie sanno che manca."""
    momentum: dict = {}
    volatility: dict = {}
    trend: dict = {}
    for ticker, series in history.items():
        px = [p for _, p in series]
        n = len(px)
        if n < MIN_OBS:
            continue
        entry = {"n_obs": n, "source": "price_history"}
        if n > MOMENTUM_1M:
            entry["return_1m"] = round(px[-1] / px[-1 - MOMENTUM_1M] - 1.0, 4)
        if n > MOMENTUM_3M:
            entry["return_3m"] = round(px[-1] / px[-1 - MOMENTUM_3M] - 1.0, 4)
        if "return_3m" in entry:
            momentum[ticker] = entry

        rets = [px[i] / px[i - 1] - 1.0 for i in range(1, n)]
        window = rets[-VOL_WINDOW:]
        if len(window) >= 20:
            mean = sum(window) / len(window)
            var = sum((r - mean) ** 2 for r in window) / (len(window) - 1)
            volatility[ticker] = {"vol_60d": round(math.sqrt(var * TRADING_DAYS), 4)}

        if n >= TREND_WINDOW:
            ma = sum(px[-TREND_WINDOW:]) / TREND_WINDOW
            trend[ticker] = {"above_ma200": px[-1] > ma}
    return {"momentum": momentum, "volatility": volatility, "trend": trend}

# ---------------------------------------------------------------------------
# Parte 2 - storico persistito (data/price_history.json): prezzi, FX, benchmark.
# Serve a ricostruire l'equity con prezzi e cambi reali e a confrontare i benchmark.
# Additivo: i valori gia' presenti non vengono mai cancellati.
# ---------------------------------------------------------------------------

PRICE_HISTORY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "price_history.json"
)


def load_price_history(path: str = PRICE_HISTORY_PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_price_history(history: dict, path: str = PRICE_HISTORY_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ordered = {t: dict(sorted(days.items())) for t, days in sorted(history.items())}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=1, ensure_ascii=False)
        f.write("\n")


def record_prices(prices: dict, day: str | None = None, path: str = PRICE_HISTORY_PATH) -> None:
    """Registra i prezzi reali di oggi (l'ultimo valore del giorno vince)."""
    if not prices:
        return
    day = day or str(date.today())
    history = load_price_history(path)
    for ticker, price in prices.items():
        history.setdefault(ticker, {})[day] = round(float(price), 6)
    save_price_history(history, path)


def fetch_yfinance_history(tickers: list[str], start: str) -> dict:
    """Scarica le chiusure giornaliere da Yahoo Finance. Best-effort: {} se fallisce."""
    try:
        import yfinance as yf

        raw = yf.download(
            tickers, start=start, auto_adjust=True, progress=False, threads=False
        )
    except Exception as e:  # rete, rate-limit, import
        print(f"[WARN] price history download failed: {e}")
        return {}
    if raw is None or raw.empty:
        return {}
    close = raw["Close"] if "Close" in raw.columns else raw
    out: dict[str, dict[str, float]] = {}
    if len(tickers) == 1 and not hasattr(close, "columns"):
        close = close.to_frame(tickers[0])
    for ticker in tickers:
        if ticker not in close.columns:
            continue
        series = close[ticker].dropna()
        out[ticker] = {d.strftime("%Y-%m-%d"): round(float(v), 6) for d, v in series.items()}
    return out


def merge_into_history(fetched: dict, path: str = PRICE_HISTORY_PATH) -> int:
    """Unisce {ticker: {data: prezzo}} allo storico senza sovrascrivere. Ritorna i punti nuovi."""
    history = load_price_history(path)
    added = 0
    for ticker, days in fetched.items():
        known = history.setdefault(ticker, {})
        for d, v in days.items():
            if d not in known:
                known[d] = v
                added += 1
    if added:
        save_price_history(history, path)
    return added


def update_price_history(tickers: list[str], start: str, path: str = PRICE_HISTORY_PATH) -> int:
    """Aggiunge allo storico i prezzi scaricati, senza sovrascrivere quelli esistenti."""
    return merge_into_history(fetch_yfinance_history(tickers, start), path)


def update_fx_history(fx_tickers: dict, start: str, path: str = PRICE_HISTORY_PATH) -> int:
    """fx_tickers = {"USD": "USDEUR=X", ...} -> salva con chiave "FX:USD" (tasso verso EUR)."""
    fetched = fetch_yfinance_history(list(fx_tickers.values()), start)
    renamed = {f"FX:{ccy}": fetched[sym] for ccy, sym in fx_tickers.items() if sym in fetched}
    return merge_into_history(renamed, path)


def record_fx(fx_rates: dict, day: str | None = None, path: str = PRICE_HISTORY_PATH) -> None:
    """Registra gli FX di oggi (solo valute non-EUR, GBp escluso: derivato da GBP)."""
    day = day or str(date.today())
    record_prices(
        {f"FX:{c}": r for c, r in fx_rates.items() if c not in ("EUR", "GBp") and r},
        day,
        path,
    )


# ---------------------------------------------------------------------------
# Benchmark: Yahoo -> Tiingo (ticker USA) / Alpha Vantage (ticker europei)
# ---------------------------------------------------------------------------


def _fetch_tiingo_history(ticker: str, start: str) -> dict:
    key = os.getenv("TIINGO_API_KEY", "")
    if not key:
        return {}
    try:
        import requests

        resp = requests.get(
            f"https://api.tiingo.com/tiingo/daily/{ticker}/prices",
            params={"startDate": start, "token": key},
            timeout=20,
        )
        if resp.status_code != 200:
            return {}
        return {
            row["date"][:10]: round(float(row.get("adjClose") or row["close"]), 6)
            for row in resp.json()
        }
    except Exception as e:
        print(f"[WARN] Tiingo history failed for {ticker}: {e}")
        return {}


def _fetch_alpha_vantage_history(ticker: str) -> dict:
    key = os.getenv("ALPHA_VANTAGE_KEY", "")
    if not key:
        return {}
    symbol = ticker.replace(".MI", ".MIL").replace(".L", ".LON")
    try:
        import requests

        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "compact",
                "apikey": key,
            },
            timeout=20,
        )
        series = resp.json().get("Time Series (Daily)", {})
        return {d: round(float(v["4. close"]), 6) for d, v in series.items()}
    except Exception as e:
        print(f"[WARN] Alpha Vantage history failed for {ticker}: {e}")
        return {}


def refresh_benchmarks(
    benchmarks: list[str], default_start: str, path: str = PRICE_HISTORY_PATH
) -> int:
    """Aggiorna lo storico dei benchmark. Non solleva mai eccezioni. Ritorna i punti aggiunti."""
    today = str(date.today())
    history = load_price_history(path)
    stale = [t for t in benchmarks if max(history.get(t, {"": 0}), default="") < today]
    if not stale:
        return 0

    starts = {t: max(history.get(t, {default_start: 0}), default=default_start) for t in stale}
    fetched = fetch_yfinance_history(stale, min(starts.values()))
    for ticker in stale:
        if fetched.get(ticker):
            continue
        if "." not in ticker:
            fetched[ticker] = _fetch_tiingo_history(ticker, starts[ticker])
        if not fetched.get(ticker):
            fetched[ticker] = _fetch_alpha_vantage_history(ticker)

    added = 0
    for ticker, days in fetched.items():
        known = history.setdefault(ticker, {})
        for d, v in days.items():
            if d not in known:
                known[d] = v
                added += 1
    if added:
        save_price_history(history, path)
    return added


def combined_history(
    portfolios_dir: str = PORTFOLIOS_DIR, path: str = PRICE_HISTORY_PATH
) -> dict[str, list[tuple[str, float]]]:
    """Storico per ticker [(giorno, prezzo)]: per ognuno la serie piu' lunga tra quella
    ricostruita dai log e quella persistita in data/price_history.json.

    I titoli con prezzi spesso mancanti nei log (i .MI) hanno storico completo nel file
    persistito, e quindi segnali (momentum...) calcolabili invece che omessi."""
    out = dict(load_history(portfolios_dir))
    for ticker, days in load_price_history(path).items():
        if ":" in ticker:  # chiavi speciali: FX:<valuta>, DIV:<ticker>
            continue
        series = sorted(days.items())
        if len(series) > len(out.get(ticker, [])):
            out[ticker] = series
    return out


# ---------------------------------------------------------------------------
# Dividendi (chiavi "DIV:<ticker>" -> {data ex-dividend: importo per azione in valuta locale}).
# Servono a stimare quanto le strategie non hanno incassato: la simulazione accredita solo
# la variazione di prezzo, mentre i benchmark sono "total return".
# ---------------------------------------------------------------------------


def fetch_dividends_history(tickers: list[str], start: str) -> dict:
    """Dividendi per azione da Yahoo Finance. Best-effort: {} se fallisce.

    Gli importi sono nella stessa unita' dei prezzi (per i titoli .L, pence)."""
    try:
        import yfinance as yf
    except ImportError:
        return {}
    out: dict[str, dict[str, float]] = {}
    for ticker in tickers:
        try:
            series = yf.Ticker(ticker).dividends
        except Exception as e:
            print(f"[WARN] dividends download failed for {ticker}: {e}")
            continue
        if series is None or len(series) == 0:
            continue
        days = {
            d.strftime("%Y-%m-%d"): round(float(v), 6)
            for d, v in series.items()
            if d.strftime("%Y-%m-%d") >= start and float(v) > 0
        }
        if days:
            out[f"DIV:{ticker}"] = days
    return out


def update_dividends_history(tickers: list[str], start: str, path: str = PRICE_HISTORY_PATH) -> int:
    """Aggiunge i dividendi allo storico persistito, senza sovrascrivere. Ritorna i punti nuovi."""
    return merge_into_history(fetch_dividends_history(tickers, start), path)


def dividends_by_ticker(price_history: dict) -> dict[str, dict[str, float]]:
    """{ticker: {data: importo}} estratto dalle chiavi DIV:<ticker> dello storico persistito."""
    return {k[4:]: v for k, v in price_history.items() if k.startswith("DIV:")}
