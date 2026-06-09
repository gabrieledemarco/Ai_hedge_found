import time
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

_cache: dict = {"prices": None, "timestamp": 0.0}


def _fetch_one(ticker: str) -> tuple[str, float]:
    tk = yf.Ticker(ticker)
    hist = tk.history(period="1d")
    if hist.empty:
        hist = tk.history(period="5d")
    if not hist.empty:
        return ticker, float(hist["Close"].iloc[-1])
    return ticker, 0.0


def get_live_prices(tickers: list[str], ttl: int = 60) -> dict[str, float]:
    now = time.time()
    if _cache["prices"] and (now - _cache["timestamp"]) < ttl:
        return _cache["prices"]

    prices: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        fut = {pool.submit(_fetch_one, t): t for t in tickers}
        for f in as_completed(fut):
            t, p = f.result()
            if p > 0:
                prices[t] = p

    for t in tickers:
        if t not in prices:
            fallback = 150.0 if t.endswith(".L") or t.endswith(".MI") else 100.0
            prices[t] = fallback

    _cache["prices"] = prices
    _cache["timestamp"] = now
    return prices
