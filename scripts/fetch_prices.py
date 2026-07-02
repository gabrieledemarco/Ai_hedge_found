"""
Price fetcher — IB Gateway (primary when available), Tiingo, Alpha Vantage, yfinance.

Fallback chain:
  Level 0: IB Client Portal Gateway — when IB_ACCOUNT + IB_GATEWAY_URL are set and
           the session is authenticated. Covers all markets (US, LSE, Borsa Italiana)
           with a single authenticated session; no rate limits on historical bars.
  Level 1: Tiingo — US stocks (NASDAQ/NYSE), 1000 req/day free.
  Level 2: Alpha Vantage — European stocks + US fallback, 25 req/day (5 req/min).
  Level 3: yfinance bulk — last resort; often blocked from GitHub Actions IPs.

Day-level price cache (data/prices_cache.json) persists prices across pipeline runs
within the same calendar day, reducing external API calls.
"""

import json
import os
import time
from datetime import date, timedelta

import requests
import yfinance as yf

TIINGO_KEY = os.getenv("TIINGO_API_KEY", "")
AV_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

_PRICES_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "prices_cache.json")

# Alpha Vantage symbol format for European tickers
_AV_SYMBOL = {
    "ULVR.L":  "ULVR.LON",
    "HSBA.L":  "HSBA.LON",
    "BP.L":    "BP.LON",
    "GSK.L":   "GSK.LON",
    "RIO.L":   "RIO.LON",
    "ENI.MI":  "ENI.MIL",
    "ISP.MI":  "ISP.MIL",
    "ENEL.MI": "ENEL.MIL",
    "LDO.MI":  "LDO.MIL",
    "MONC.MI": "MONC.MIL",
}


# ── Day-level price cache ─────────────────────────────────────────────────────

def _load_day_cache() -> dict:
    try:
        with open(_PRICES_CACHE_PATH) as f:
            data = json.load(f)
        if data.get("date") == str(date.today()):
            return data.get("prices", {})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {}


def _save_day_cache(prices: dict) -> None:
    os.makedirs(os.path.dirname(_PRICES_CACHE_PATH), exist_ok=True)
    with open(_PRICES_CACHE_PATH, "w") as f:
        json.dump({"date": str(date.today()), "prices": prices}, f, indent=2, sort_keys=True)


# ── Level 0: IB Client Portal Gateway ────────────────────────────────────────

def _fetch_ib(
    tickers: list[str], universe: dict
) -> tuple[dict[str, float], set[str]]:
    """Fetch prices via IB Client Portal Gateway (when available and authenticated)."""
    try:
        from ib_broker import get_broker  # imported here to avoid hard dependency
    except ImportError:
        return {}, set(tickers)

    broker = get_broker()
    if not broker.is_available():
        return {}, set(tickers)

    print("[INFO] IB Gateway is authenticated — fetching prices via IB...")
    tickers_exchange = [
        (t, universe.get(t, {}).get("exchange", "NASDAQ")) for t in tickers
    ]
    prices = broker.get_market_prices(tickers_exchange)
    failed = {t for t in tickers if t not in prices}
    return prices, failed


# ── Level 1: Tiingo (US stocks) ───────────────────────────────────────────────

def _fetch_tiingo(tickers: list[str]) -> tuple[dict[str, float], set[str]]:
    if not TIINGO_KEY:
        print("[WARN] TIINGO_API_KEY not set — skipping Tiingo")
        return {}, set(tickers)

    prices: dict[str, float] = {}
    failed: set[str] = set()
    start_date = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    for ticker in tickers:
        url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"
        params = {"startDate": start_date, "token": TIINGO_KEY}
        try:
            resp = session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"[WARN] Tiingo HTTP {resp.status_code} for {ticker}: {resp.text[:120]}")
                failed.add(ticker)
                continue
            data = resp.json()
            if not data:
                print(f"[WARN] Tiingo: empty response for {ticker}")
                failed.add(ticker)
                continue
            row = data[-1]
            close = row.get("adjClose") or row.get("close")
            if close is None:
                print(f"[WARN] Tiingo: no close price for {ticker}")
                failed.add(ticker)
                continue
            prices[ticker] = float(close)
            print(f"  {ticker}: {prices[ticker]:.4f} (tiingo)")
        except Exception as e:
            print(f"[WARN] Tiingo failed for {ticker}: {e}")
            failed.add(ticker)

    return prices, failed


# ── Level 2: Alpha Vantage (European + fallback for US) ───────────────────────

def _fetch_alpha_vantage(tickers: list[str]) -> tuple[dict[str, float], set[str]]:
    if not AV_KEY:
        print("[WARN] ALPHA_VANTAGE_KEY not set — skipping Alpha Vantage")
        return {}, set(tickers)

    prices: dict[str, float] = {}
    failed: set[str] = set()

    session = requests.Session()

    for i, ticker in enumerate(tickers):
        symbol = _AV_SYMBOL.get(ticker, ticker)
        params = {"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": AV_KEY}
        try:
            resp = session.get(
                "https://www.alphavantage.co/query", params=params, timeout=15
            )
            if resp.status_code != 200:
                print(f"[WARN] Alpha Vantage HTTP {resp.status_code} for {ticker}")
                failed.add(ticker)
            else:
                data = resp.json()
                quote = data.get("Global Quote", {})
                price_str = quote.get("05. price", "")
                if price_str:
                    prices[ticker] = float(price_str)
                    print(f"  {ticker}: {prices[ticker]:.4f} (alpha_vantage/{symbol})")
                else:
                    note = data.get("Note") or data.get("Information") or "empty quote"
                    print(f"[WARN] Alpha Vantage no price for {ticker} ({symbol}): {str(note)[:100]}")
                    failed.add(ticker)
        except Exception as e:
            print(f"[WARN] Alpha Vantage failed for {ticker}: {e}")
            failed.add(ticker)

        # Free tier: 5 req/min → wait 13s between calls (except after last)
        if i < len(tickers) - 1:
            time.sleep(13)

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
    """Fetch closing prices for all tickers with day-level caching.

    Fallback chain: IB Gateway → Tiingo (US) → Alpha Vantage (EU/US) → yfinance bulk.
    IB Gateway is used when IB_ACCOUNT is set and the session is authenticated;
    it covers all markets with no per-ticker rate limits.
    Returns (prices_dict, failed_set).
    """
    if universe is None:
        universe = {}

    all_prices: dict[str, float] = {}

    # Day-level cache — reuse prices already fetched today
    cached = _load_day_cache()
    for t in tickers:
        if t in cached:
            all_prices[t] = cached[t]
    missing = [t for t in tickers if t not in all_prices]

    if cached and len(cached) >= len(tickers) - len(missing):
        print(f"[INFO] {len(all_prices)} prices from today's cache.")

    if not missing:
        return all_prices, set()

    # Level 0: IB Gateway — covers all markets when authenticated
    ib_prices, ib_failed = _fetch_ib(missing, universe)
    all_prices.update(ib_prices)
    missing = sorted(ib_failed)

    if not missing:
        updated_cache = {**cached, **{t: p for t, p in all_prices.items()}}
        _save_day_cache(updated_cache)
        print(f"[INFO] All {len(tickers)} prices resolved via IB Gateway.")
        return all_prices, set()

    # Split remaining by exchange for Tiingo/AV fallback
    us_tickers = [
        t for t in missing
        if universe.get(t, {}).get("exchange") in ("NASDAQ", "NYSE")
    ]
    remaining_tickers = [t for t in missing if t not in us_tickers]

    # Level 1: Tiingo for US stocks
    if us_tickers:
        print(f"[INFO] Fetching {len(us_tickers)} US prices via Tiingo...")
        tiingo_prices, tiingo_failed = _fetch_tiingo(us_tickers)
        all_prices.update(tiingo_prices)
        remaining_tickers.extend(sorted(tiingo_failed))

    # Level 2: Alpha Vantage for European + any Tiingo failures
    if remaining_tickers:
        print(f"[INFO] Fetching {len(remaining_tickers)} prices via Alpha Vantage...")
        av_prices, av_failed = _fetch_alpha_vantage(remaining_tickers)
        all_prices.update(av_prices)
        remaining_tickers = sorted(av_failed)

    # Level 3: yfinance bulk (last resort)
    if remaining_tickers:
        print(f"[INFO] {len(remaining_tickers)} tickers still missing — yfinance bulk fallback...")
        yf_prices, yf_failed = _fetch_yfinance_bulk(remaining_tickers)
        all_prices.update(yf_prices)
        failed_final = set(yf_failed)
    else:
        failed_final = set()

    # Persist newly fetched prices to day cache
    updated_cache = {**cached, **{t: p for t, p in all_prices.items()}}
    _save_day_cache(updated_cache)

    if failed_final:
        print(f"[WARN] {len(failed_final)}/{len(tickers)} prices unavailable: {sorted(failed_final)}")
    else:
        print(f"[INFO] All {len(tickers)} prices resolved.")

    return all_prices, failed_final
