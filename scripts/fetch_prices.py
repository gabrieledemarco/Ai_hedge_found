"""
Price fetcher using investing.com data via the investiny library.
investiny is the maintained successor to the discontinued investpy library.

Flow:
  1. investing.com (investiny) — primary source for all 20 tickers
  2. yfinance bulk download   — fallback for tickers investiny misses
                                 (single HTTP request, less rate-limited than individual calls)

investing.com ID resolution:
  - IDs are cached in data/investing_ids.json (committed to repo)
  - On cache miss, investiny.search_assets() resolves the ID automatically
  - Cache is updated and committed by the pipeline
"""

import json
import os
import time
from datetime import date, timedelta

try:
    from investiny import historical_data, search_assets
    _INVESTINY_OK = True
except ImportError:
    _INVESTINY_OK = False
    print("[WARN] investiny not installed — install with: pip install investiny")

import yfinance as yf

# Persistent cache: maps our ticker symbol → investing.com numeric ID
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "investing_ids.json")

# investing.com exchange names as used by investiny search
_EXCHANGE_MAP = {
    "NASDAQ": "NASDAQ",
    "NYSE": "NYSE",
    "FTSE": "LSE",
    "BIT": "Borsa Italiana",
}

# Company names for investiny.search_assets() lookup (avoids ticker-format issues)
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


# ── ID cache helpers ──────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        with open(_CACHE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    with open(_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _resolve_id(ticker: str, exchange_key: str, cache: dict) -> int | None:
    """Return cached investing.com ID or search for it via investiny."""
    if ticker in cache:
        return int(cache[ticker])

    company = _COMPANY_NAMES.get(ticker, ticker.replace(".L", "").replace(".MI", ""))
    exchange = _EXCHANGE_MAP.get(exchange_key, exchange_key)

    try:
        results = search_assets(query=company, limit=5, type="stock", exchange=exchange)
        if results:
            investing_id = int(results[0]["id"])
            cache[ticker] = investing_id
            print(f"  [cache] {ticker} → investing.com ID {investing_id}")
            return investing_id
    except Exception as e:
        print(f"[WARN] investiny search failed for {ticker}: {e}")

    return None


# ── Level 1: investing.com via investiny ──────────────────────────────────────

def _fetch_investing(tickers: list[str], universe: dict) -> tuple[dict[str, float], set[str]]:
    if not _INVESTINY_OK:
        return {}, set(tickers)

    cache = _load_cache()
    prices: dict[str, float] = {}
    failed: set[str] = set()
    cache_updated = False

    from_date = (date.today() - timedelta(days=7)).strftime("%m/%d/%Y")
    to_date = date.today().strftime("%m/%d/%Y")

    for ticker in tickers:
        exchange_key = universe.get(ticker, {}).get("exchange", "")
        prev_len = len(cache)

        investing_id = _resolve_id(ticker, exchange_key, cache)
        if len(cache) > prev_len:
            cache_updated = True

        if investing_id is None:
            print(f"[WARN] investiny: no ID for {ticker}")
            failed.add(ticker)
            continue

        try:
            data = historical_data(
                investing_id=investing_id,
                from_date=from_date,
                to_date=to_date,
            )
            closes = [v for v in (data.get("close") or []) if v is not None]
            if closes:
                price = float(closes[-1])
                prices[ticker] = price
                print(f"  {ticker}: {price:.4f} (investing.com)")
            else:
                print(f"[WARN] investiny: empty data for {ticker}")
                failed.add(ticker)
        except Exception as e:
            print(f"[WARN] investiny failed for {ticker}: {e}")
            failed.add(ticker)

        time.sleep(0.5)

    if cache_updated:
        _save_cache(cache)

    return prices, failed


# ── Level 2: yfinance bulk (single request for all tickers) ──────────────────

def _fetch_yfinance_bulk(tickers: list[str]) -> tuple[dict[str, float], set[str]]:
    """One yf.download() call for all tickers — 1 HTTP request, avoids rate limiting."""
    if not tickers:
        return {}, set()

    prices: dict[str, float] = {}
    failed: set[str] = set()

    try:
        raw = yf.download(
            tickers,
            period="5d",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if raw.empty:
            return {}, set(tickers)

        close = raw["Close"] if "Close" in raw.columns else raw

        if len(tickers) == 1:
            series = close.dropna()
            if not series.empty:
                prices[tickers[0]] = float(series.iloc[-1])
                print(f"  {tickers[0]}: {prices[tickers[0]]:.4f} (yfinance-bulk fallback)")
            else:
                failed.add(tickers[0])
        else:
            for t in tickers:
                try:
                    series = close[t].dropna()
                    if not series.empty:
                        prices[t] = float(series.iloc[-1])
                        print(f"  {t}: {prices[t]:.4f} (yfinance-bulk fallback)")
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
    """Fetch prices: investing.com primary, yfinance bulk fallback.

    Returns (prices_dict, failed_set).
    failed_set: tickers with no price — pipeline skips trading for these.
    """
    if universe is None:
        universe = {}

    all_prices: dict[str, float] = {}
    remaining = list(tickers)

    # Level 1: investing.com
    print("[INFO] Fetching prices via investing.com (investiny)...")
    inv_prices, inv_failed = _fetch_investing(remaining, universe)
    all_prices.update(inv_prices)
    remaining = sorted(inv_failed)

    if not remaining:
        print(f"[INFO] All {len(tickers)} prices from investing.com.")
        return all_prices, set()

    # Level 2: yfinance bulk for whatever investiny missed
    print(f"[INFO] investiny missed {len(remaining)} tickers — yfinance bulk fallback...")
    yf_prices, yf_failed = _fetch_yfinance_bulk(remaining)
    all_prices.update(yf_prices)
    remaining = sorted(yf_failed)

    failed_final = set(remaining)
    if failed_final:
        print(f"[WARN] {len(failed_final)}/{len(tickers)} prices unavailable: {sorted(failed_final)}")
    else:
        print(f"[INFO] All {len(tickers)} prices resolved.")

    return all_prices, failed_final
