"""
Price fetcher — Stooq primary (no API key, not blocked from CI),
                investiny secondary (investing.com, works locally),
                yfinance bulk tertiary fallback.

Both investing.com and Yahoo Finance block GitHub Actions IP ranges (403/429).
Stooq is a free service that reliably serves data from CI environments.

Stooq symbol format:
  US  (NASDAQ/NYSE): aapl.us, msft.us, …
  UK  (FTSE/LSE):    ulvr.uk, hsba.uk, …
  IT  (BIT/Milan):   eni.it,  isp.it,  …
"""

import io
import json
import os
import time
from datetime import date, timedelta

import pandas as pd
import requests
import yfinance as yf

try:
    from investiny import historical_data, search_assets
    _INVESTINY_OK = True
except ImportError:
    _INVESTINY_OK = False

_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "investing_ids.json")

_STOOQ_SUFFIX = {
    "NASDAQ": ".us",
    "NYSE":   ".us",
    "FTSE":   ".uk",
    "BIT":    ".it",
}

_EXCHANGE_MAP = {
    "NASDAQ": "NASDAQ",
    "NYSE":   "NYSE",
    "FTSE":   "LSE",
    "BIT":    "Borsa Italiana",
}

_COMPANY_NAMES = {
    "AAPL":    "Apple",
    "MSFT":    "Microsoft",
    "GOOGL":   "Alphabet",
    "AMZN":    "Amazon",
    "TSLA":    "Tesla",
    "JPM":     "JPMorgan Chase",
    "NVDA":    "NVIDIA",
    "JNJ":     "Johnson Johnson",
    "V":       "Visa",
    "KO":      "Coca-Cola",
    "ULVR.L":  "Unilever",
    "HSBA.L":  "HSBC Holdings",
    "BP.L":    "BP",
    "GSK.L":   "GSK",
    "RIO.L":   "Rio Tinto",
    "ENI.MI":  "Eni",
    "ISP.MI":  "Intesa Sanpaolo",
    "ENEL.MI": "Enel",
    "LDO.MI":  "Leonardo",
    "MONC.MI": "Moncler",
}


# ── Level 1: Stooq ────────────────────────────────────────────────────────────

def _ticker_to_stooq(ticker: str, exchange_key: str) -> str:
    base = ticker.replace(".L", "").replace(".MI", "").lower()
    suffix = _STOOQ_SUFFIX.get(exchange_key, ".us")
    return base + suffix


def _fetch_stooq(tickers: list[str], universe: dict) -> tuple[dict[str, float], set[str]]:
    prices: dict[str, float] = {}
    failed: set[str] = set()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; price-fetcher/1.0)"
    })

    for ticker in tickers:
        exchange_key = universe.get(ticker, {}).get("exchange", "NASDAQ")
        stooq_sym = _ticker_to_stooq(ticker, exchange_key)
        url = f"https://stooq.com/q/d/l/?s={stooq_sym}&i=d"
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200 or not resp.text.strip():
                print(f"[WARN] stooq: HTTP {resp.status_code} for {stooq_sym}")
                failed.add(ticker)
                continue

            df = pd.read_csv(io.StringIO(resp.text))
            if df.empty or "Close" not in df.columns:
                print(f"[WARN] stooq: empty/no-close for {stooq_sym}")
                failed.add(ticker)
                continue

            close_val = df["Close"].dropna().iloc[-1]
            prices[ticker] = float(close_val)
            print(f"  {ticker}: {prices[ticker]:.4f} (stooq/{stooq_sym})")
        except Exception as e:
            print(f"[WARN] stooq failed for {ticker} ({stooq_sym}): {e}")
            failed.add(ticker)

        time.sleep(0.3)

    return prices, failed


# ── Level 2: investing.com via investiny ──────────────────────────────────────

def _load_id_cache() -> dict:
    try:
        with open(_CACHE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_id_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    with open(_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _resolve_investing_id(ticker: str, exchange_key: str, cache: dict) -> int | None:
    if ticker in cache:
        return int(cache[ticker])
    company = _COMPANY_NAMES.get(ticker, ticker.replace(".L", "").replace(".MI", ""))
    exchange = _EXCHANGE_MAP.get(exchange_key, exchange_key)
    try:
        results = search_assets(query=company, limit=5, type="stock", exchange=exchange)
        if results:
            investing_id = int(results[0]["id"])
            cache[ticker] = investing_id
            return investing_id
    except Exception as e:
        print(f"[WARN] investiny search failed for {ticker}: {e}")
    return None


def _fetch_investiny(tickers: list[str], universe: dict) -> tuple[dict[str, float], set[str]]:
    if not _INVESTINY_OK:
        return {}, set(tickers)

    cache = _load_id_cache()
    prices: dict[str, float] = {}
    failed: set[str] = set()
    cache_updated = False

    from_date = (date.today() - timedelta(days=7)).strftime("%m/%d/%Y")
    to_date = date.today().strftime("%m/%d/%Y")

    for ticker in tickers:
        exchange_key = universe.get(ticker, {}).get("exchange", "")
        n_before = len(cache)
        investing_id = _resolve_investing_id(ticker, exchange_key, cache)
        if len(cache) > n_before:
            cache_updated = True

        if investing_id is None:
            failed.add(ticker)
            continue

        try:
            data = historical_data(investing_id=investing_id, from_date=from_date, to_date=to_date)
            closes = [v for v in (data.get("close") or []) if v is not None]
            if closes:
                prices[ticker] = float(closes[-1])
                print(f"  {ticker}: {prices[ticker]:.4f} (investing.com)")
            else:
                failed.add(ticker)
        except Exception as e:
            print(f"[WARN] investiny failed for {ticker}: {e}")
            failed.add(ticker)

        time.sleep(0.5)

    if cache_updated:
        _save_id_cache(cache)

    return prices, failed


# ── Level 3: yfinance bulk ────────────────────────────────────────────────────

def _fetch_yfinance_bulk(tickers: list[str]) -> tuple[dict[str, float], set[str]]:
    if not tickers:
        return {}, set()

    prices: dict[str, float] = {}
    failed: set[str] = set()

    try:
        raw = yf.download(tickers, period="5d", auto_adjust=True, progress=False, threads=False)
        if raw.empty:
            return {}, set(tickers)

        close = raw["Close"] if "Close" in raw.columns else raw

        if len(tickers) == 1:
            series = close.dropna()
            if not series.empty:
                prices[tickers[0]] = float(series.iloc[-1])
                print(f"  {tickers[0]}: {prices[tickers[0]]:.4f} (yfinance-bulk)")
            else:
                failed.add(tickers[0])
        else:
            for t in tickers:
                try:
                    series = close[t].dropna()
                    if not series.empty:
                        prices[t] = float(series.iloc[-1])
                        print(f"  {t}: {prices[t]:.4f} (yfinance-bulk)")
                    else:
                        failed.add(t)
                except (KeyError, IndexError):
                    failed.add(t)
    except Exception as e:
        print(f"[WARN] yfinance bulk failed: {e}")
        failed = set(tickers)

    return prices, failed


# ── Public API ────────────────────────────────────────────────────────────────

def get_prices(tickers: list[str], universe: dict | None = None) -> tuple[dict[str, float], set[str]]:
    """Fetch closing prices with three-level fallback.

    Returns (prices_dict, failed_set).
    failed_set: tickers with no reliable price — pipeline skips trading for these.
    """
    if universe is None:
        universe = {}

    all_prices: dict[str, float] = {}

    # Level 1: Stooq (no key, works from GitHub Actions)
    print("[INFO] Fetching prices via Stooq...")
    stooq_prices, stooq_failed = _fetch_stooq(list(tickers), universe)
    all_prices.update(stooq_prices)
    remaining = sorted(stooq_failed)

    if not remaining:
        print(f"[INFO] All {len(tickers)} prices from Stooq.")
        return all_prices, set()

    # Level 2: investing.com via investiny (works locally, blocked on GH Actions)
    print(f"[INFO] Stooq missed {len(remaining)} tickers — trying investiny...")
    inv_prices, inv_failed = _fetch_investiny(remaining, universe)
    all_prices.update(inv_prices)
    remaining = sorted(inv_failed)

    if not remaining:
        print(f"[INFO] All {len(tickers)} prices resolved (stooq + investiny).")
        return all_prices, set()

    # Level 3: yfinance bulk
    print(f"[INFO] {len(remaining)} tickers still missing — yfinance bulk fallback...")
    yf_prices, yf_failed = _fetch_yfinance_bulk(remaining)
    all_prices.update(yf_prices)

    failed_final = set(yf_failed)
    if failed_final:
        print(f"[WARN] {len(failed_final)}/{len(tickers)} prices unavailable: {sorted(failed_final)}")
    else:
        print(f"[INFO] All {len(tickers)} prices resolved.")

    return all_prices, failed_final
