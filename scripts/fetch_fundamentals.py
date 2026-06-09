import os
import json
import time
from datetime import datetime, timezone

import yfinance as yf


def score_fundamental(info: dict) -> float:
    """
    Calcola F-score normalizzato 0-1 da metriche yfinance.
    Criteri: basso PE, alto ROE, positivo FCF, basso D/E.
    """
    score = 0.0
    count = 0

    # P/E basso e' buono (< 20 ottimo, > 40 pessimo)
    pe = info.get("trailingPE")
    if pe and pe > 0:
        pe_score = max(0.0, min(1.0, (40 - pe) / 30))
        score += pe_score
        count += 1

    # ROE alto e' buono (> 15% ottimo)
    roe = info.get("returnOnEquity")
    if roe is not None:
        roe_score = max(0.0, min(1.0, roe / 0.25))
        score += roe_score
        count += 1

    # FCF positivo e' buono
    fcf = info.get("freeCashflow")
    mkt_cap = info.get("marketCap")
    if fcf and mkt_cap and mkt_cap > 0:
        fcf_yield = fcf / mkt_cap
        fcf_score = max(0.0, min(1.0, fcf_yield / 0.05))
        score += fcf_score
        count += 1

    # Debt/Equity basso e' buono (< 50% ottimo, > 200% pessimo)
    de = info.get("debtToEquity")
    if de is not None and de >= 0:
        de_score = max(0.0, min(1.0, (200 - de) / 200))
        score += de_score
        count += 1

    return round(score / count, 4) if count > 0 else 0.5


def fetch_all_fundamentals(universe: dict) -> dict:
    results = {}
    tickers = list(universe.keys())

    print(f"[INFO] Fetching fundamentals for {len(tickers)} tickers...")
    for i, ticker in enumerate(tickers):
        print(f"  [{i+1}/{len(tickers)}] {ticker}...")
        try:
            info = yf.Ticker(ticker).info
            f_score = score_fundamental(info)
            results[ticker] = {
                "pe_ratio": info.get("trailingPE"),
                "pb_ratio": info.get("priceToBook"),
                "roe": info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
                "market_cap": info.get("marketCap"),
                "revenue_growth": info.get("revenueGrowth"),
                "f_score": f_score,
            }
        except Exception as e:
            print(f"[WARN] Fundamentals failed for {ticker}: {e}")
            results[ticker] = {"f_score": 0.5}
        time.sleep(0.5)

    return results


def fetch_momentum(universe: dict) -> dict:
    """Calcola momentum 3m e 1m per ogni ticker."""
    results = {}
    tickers = list(universe.keys())

    print(f"[INFO] Fetching momentum for {len(tickers)} tickers...")
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period="4mo")
            if len(hist) >= 60:
                price_now = float(hist["Close"].iloc[-1])
                price_3m = (
                    float(hist["Close"].iloc[-63])
                    if len(hist) >= 63
                    else float(hist["Close"].iloc[0])
                )
                price_1m = (
                    float(hist["Close"].iloc[-21]) if len(hist) >= 21 else price_now
                )
                ret_3m = (price_now - price_3m) / price_3m if price_3m > 0 else 0.0
                ret_1m = (price_now - price_1m) / price_1m if price_1m > 0 else 0.0
                results[ticker] = {
                    "return_3m": round(ret_3m, 4),
                    "return_1m": round(ret_1m, 4),
                }
            else:
                results[ticker] = {"return_3m": 0.0, "return_1m": 0.0}
        except Exception as e:
            print(f"[WARN] Momentum failed for {ticker}: {e}")
            results[ticker] = {"return_3m": 0.0, "return_1m": 0.0}

    return results


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(__file__))
    from config import UNIVERSE

    fundamentals = fetch_all_fundamentals(UNIVERSE)
    momentum = fetch_momentum(UNIVERSE)

    signals_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "signals.json"
    )
    try:
        with open(signals_path) as f:
            signals = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        signals = {}

    signals["fundamentals"] = fundamentals
    signals["momentum"] = momentum
    signals["fundamentals_updated"] = datetime.now(timezone.utc).isoformat()

    with open(signals_path, "w") as f:
        json.dump(signals, f, indent=2)

    print(f"[OK] Fundamentals + momentum saved to {signals_path}")
