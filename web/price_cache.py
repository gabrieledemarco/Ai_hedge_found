import time
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

_cache: dict = {"prices": None, "timestamp": 0.0}


def _fetch_one(ticker: str) -> tuple[str, float | None]:
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="1d")
        if hist.empty:
            hist = tk.history(period="5d")
        if not hist.empty:
            return ticker, float(hist["Close"].iloc[-1])
        return ticker, None
    except YFRateLimitError:
        return ticker, None


def get_live_prices(tickers: list[str], ttl: int = 300) -> dict[str, float]:
    now = time.time()
    cache_age = now - _cache["timestamp"] if _cache["prices"] else float("inf")

    if _cache["prices"] and cache_age < ttl:
        return _cache["prices"]

    prices: dict[str, float] = {}
    for t in tickers:
        _, p = _fetch_one(t)
        if p is not None and p > 0:
            prices[t] = p
            print(f"  {t}: {p:.2f}")
        else:
            stale = _cache["prices"].get(t) if _cache["prices"] else None
            if stale:
                prices[t] = stale
                print(f"  {t}: {stale:.2f} (stale cache)")
            else:
                fallback = 150.0 if t.endswith(".L") or t.endswith(".MI") else 100.0
                prices[t] = fallback
                print(f"  {t}: {fallback:.2f} (fallback)")
        time.sleep(0.5)

    _cache["prices"] = prices
    _cache["timestamp"] = now
    return prices
