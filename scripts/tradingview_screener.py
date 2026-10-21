"""
TradingView Stock Screener — fetches technical signals via TradingView's
public scanner API for all universe tickers and saves to data/tv_screener.json.
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

TV_TICKER_MAP = {
    "AAPL":    "NASDAQ:AAPL",
    "MSFT":    "NASDAQ:MSFT",
    "GOOGL":   "NASDAQ:GOOGL",
    "AMZN":    "NASDAQ:AMZN",
    "TSLA":    "NASDAQ:TSLA",
    "JPM":     "NYSE:JPM",
    "NVDA":    "NASDAQ:NVDA",
    "JNJ":     "NYSE:JNJ",
    "V":       "NYSE:V",
    "KO":      "NYSE:KO",
    "ULVR.L":  "LSE:ULVR",
    "HSBA.L":  "LSE:HSBA",
    "BP.L":    "LSE:BP",
    "GSK.L":   "LSE:GSK",
    "RIO.L":   "LSE:RIO",
    "ENI.MI":  "MIL:ENI",
    "ISP.MI":  "MIL:ISP",
    "ENEL.MI": "MIL:ENEL",
    "LDO.MI":  "MIL:LDO",
    "MONC.MI": "MIL:MONC",
}

COLUMNS = [
    "Recommend.All",    # Overall technical rating (-1 to +1)
    "Recommend.MA",     # Moving averages rating
    "Recommend.Other",  # Oscillators rating
    "RSI",              # RSI 14
    "RSI[1]",           # RSI previous period
    "MACD.macd",        # MACD line
    "MACD.signal",      # MACD signal line
    "EMA20",            # 20-period EMA
    "EMA50",            # 50-period EMA
    "EMA200",           # 200-period EMA
    "SMA50",            # 50-period SMA
    "volume",           # Volume
    "change",           # % change vs previous close
    "close",            # Last price
    "ADX",              # Average Directional Index
    "Stoch.K",          # Stochastic %K
    "Stoch.D",          # Stochastic %D
    "CCI20",            # Commodity Channel Index 20
    "BB.upper",         # Bollinger Band upper
    "BB.lower",         # Bollinger Band lower
    "market_cap_basic", # Market cap (USD)
    "P/E",              # Price/Earnings ratio
    "relative_volume_10d_calc",  # Relative volume vs 10d avg
]

SCANNER_URL = "https://scanner.tradingview.com/global/scan"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}


def fetch_tv_screener(ticker_map: dict | None = None) -> dict:
    """Return dict keyed by our ticker with TradingView technical data."""
    if ticker_map is None:
        ticker_map = TV_TICKER_MAP

    tv_symbols = list(ticker_map.values())
    reverse = {v: k for k, v in ticker_map.items()}

    payload = {"symbols": {"tickers": tv_symbols}, "columns": COLUMNS}

    for attempt in range(3):
        try:
            resp = requests.post(
                SCANNER_URL, json=payload, headers=_HEADERS, timeout=25
            )
            resp.raise_for_status()
            raw = resp.json()
            break
        except Exception as e:
            if attempt == 2:
                print(f"[ERROR] TradingView API failed after 3 attempts: {e}")
                return {}
            time.sleep(2 ** attempt)

    results: dict = {}
    for item in raw.get("data", []):
        tv_sym: str = item["s"]
        vals: list = item["d"]
        row = dict(zip(COLUMNS, vals))
        our_ticker = reverse.get(tv_sym, tv_sym)
        results[our_ticker] = {
            "tv_symbol":               tv_sym,
            "recommend_all":           row.get("Recommend.All"),
            "recommend_ma":            row.get("Recommend.MA"),
            "recommend_oscillators":   row.get("Recommend.Other"),
            "rsi":                     row.get("RSI"),
            "rsi_prev":                row.get("RSI[1]"),
            "macd":                    row.get("MACD.macd"),
            "macd_signal":             row.get("MACD.signal"),
            "ema20":                   row.get("EMA20"),
            "ema50":                   row.get("EMA50"),
            "ema200":                  row.get("EMA200"),
            "sma50":                   row.get("SMA50"),
            "volume":                  row.get("volume"),
            "change_pct":              row.get("change"),
            "close":                   row.get("close"),
            "adx":                     row.get("ADX"),
            "stoch_k":                 row.get("Stoch.K"),
            "stoch_d":                 row.get("Stoch.D"),
            "cci":                     row.get("CCI20"),
            "bb_upper":                row.get("BB.upper"),
            "bb_lower":                row.get("BB.lower"),
            "market_cap":              row.get("market_cap_basic"),
            "pe_ratio":                row.get("P/E"),
            "relative_volume":         row.get("relative_volume_10d_calc"),
        }

    return results


def rating_label(val: float | None) -> str:
    if val is None:
        return "N/D"
    if val >= 0.5:
        return "Strong Buy"
    if val >= 0.1:
        return "Buy"
    if val > -0.1:
        return "Neutral"
    if val > -0.5:
        return "Sell"
    return "Strong Sell"


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(__file__))

    print(f"[INFO] Fetching TradingView screener for {len(TV_TICKER_MAP)} tickers...")
    data = fetch_tv_screener()

    out = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "tickers": data,
    }

    out_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "tv_screener.json"
    )
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    print(f"[OK] TradingView screener saved to {out_path}")
    print(f"{'Ticker':12s} {'TV Symbol':18s} {'Rating':12s} {'RSI':6s} {'Change%':8s}")
    print("-" * 60)
    for ticker, d in sorted(data.items(), key=lambda x: x[1].get("recommend_all") or 0, reverse=True):
        rec = d.get("recommend_all")
        rsi = d.get("rsi")
        chg = d.get("change_pct")
        print(
            f"{ticker:12s} {d['tv_symbol']:18s} "
            f"{rating_label(rec):12s} "
            f"{rsi or 0:6.1f} "
            f"{chg or 0:+8.2f}%"
        )
