"""
Multi-source price fetcher with 3-level fallback:

  1. Tiingo   — primary (fixed endpoint: startDate only, no invalid params)
  2. yfinance — single bulk request for all tickers (1 HTTP call vs 20, far less rate-limited)
  3. Alpha Vantage GLOBAL_QUOTE — gap-fill for individual tickers that both above miss

Tiingo ticker mapping:
  FTSE: ULVR.L → ulvr  (no .L suffix, lowercase)
  BIT:  ENI.MI → eni   (no .MI suffix, lowercase — coverage limited on Tiingo free tier)
  US:   AAPL   → aapl

Alpha Vantage symbol mapping:
  FTSE: ULVR.L → ULVR.LON
  BIT:  ENI.MI → ENI.MIL
  US:   AAPL   → AAPL
"""

import os
import time
from datetime import date, timedelta

import requests
import yfinance as yf

AV_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")
TIINGO_KEY = os.environ.get("TIINGO_API_KEY", "")

# How many tickers Alpha Vantage can fill per session before hitting the daily cap.
# Free tier = 25 req/day; 3 sessions/day → budget 8 per session (with margin).
_AV_PER_SESSION_BUDGET = 8


def _tiingo_ticker(t: str) -> str:
    return t.replace(".L", "").replace(".MI", "").lower()


def _av_symbol(t: str) -> str:
    if t.endswith(".L"):
        return t[:-2] + ".LON"
    if t.endswith(".MI"):
        return t[:-3] + ".MIL"
    return t


# ── Level 1: Tiingo ───────────────────────────────────────────────────────────

def _fetch_tiingo(tickers: list[str]) -> tuple[dict[str, float], set[str]]:
    if not TIINGO_KEY:
        print("[INFO] TIINGO_API_KEY not set — skipping Tiingo")
        return {}, set(tickers)

    start_date = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
    prices: dict[str, float] = {}
    failed: set[str] = set()

    for t in tickers:
        url = f"https://api.tiingo.com/tiingo/daily/{_tiingo_ticker(t)}/prices"
        params = {"token": TIINGO_KEY, "startDate": start_date}
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 401:
                print("[WARN] Tiingo 401 — API key invalid, skipping Tiingo entirely")
                return {}, set(tickers)
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list) and data[-1].get("adjClose") is not None:
                price = float(data[-1]["adjClose"])
                prices[t] = price
                print(f"  {t}: {price:.4f} (tiingo)")
            else:
                print(f"[WARN] Tiingo: no adjClose for {t}")
                failed.add(t)
        except requests.HTTPError as e:
            print(f"[WARN] Tiingo HTTP error for {t}: {e}")
            failed.add(t)
        except Exception as e:
            print(f"[WARN] Tiingo failed for {t}: {e}")
            failed.add(t)
        time.sleep(0.15)

    return prices, failed


# ── Level 2: yfinance bulk ────────────────────────────────────────────────────

def _fetch_yfinance_bulk(tickers: list[str]) -> tuple[dict[str, float], set[str]]:
    """Single yf.download() request for all tickers — 1 HTTP call, much less rate-limited."""
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
            print("[WARN] yfinance bulk: empty response")
            return {}, set(tickers)

        # Multi-ticker: Close is a DataFrame with ticker columns
        # Single-ticker: Close is a Series
        close = raw["Close"] if "Close" in raw.columns else raw
        if len(tickers) == 1:
            series = close.dropna() if hasattr(close, "dropna") else close
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
        print(f"[WARN] yfinance bulk download failed: {e}")
        failed = set(tickers)

    return prices, failed


# ── Level 3: Alpha Vantage GLOBAL_QUOTE (gap-fill only) ──────────────────────

def _fetch_av_quote(tickers: list[str]) -> tuple[dict[str, float], set[str]]:
    """Per-ticker AV quotes. 5 req/min → 13s between calls. Use only for small gaps."""
    if not AV_KEY or not tickers:
        return {}, set(tickers)

    prices: dict[str, float] = {}
    failed: set[str] = set()

    for i, t in enumerate(tickers):
        params = {
            "function": "GLOBAL_QUOTE",
            "symbol": _av_symbol(t),
            "apikey": AV_KEY,
        }
        try:
            resp = requests.get(
                "https://www.alphavantage.co/query", params=params, timeout=20
            )
            resp.raise_for_status()
            data = resp.json()
            if "Note" in data or "Information" in data:
                print(f"[WARN] Alpha Vantage rate limit hit after {i}/{len(tickers)} tickers")
                failed.update(tickers[i:])
                break
            price_str = data.get("Global Quote", {}).get("05. price", "")
            if price_str:
                prices[t] = float(price_str)
                print(f"  {t}: {prices[t]:.4f} (alpha_vantage)")
            else:
                print(f"[WARN] Alpha Vantage: no quote for {t} ({_av_symbol(t)})")
                failed.add(t)
        except Exception as e:
            print(f"[WARN] Alpha Vantage failed for {t}: {e}")
            failed.add(t)
        if i < len(tickers) - 1:
            time.sleep(13)  # Stay under 5/min limit

    return prices, failed


# ── Public API ────────────────────────────────────────────────────────────────

def get_prices(tickers: list[str]) -> tuple[dict[str, float], set[str]]:
    """Fetch prices with 3-level fallback. Returns (prices, failed_set).

    failed_set: tickers for which no price was obtained (should skip trading).
    """
    all_prices: dict[str, float] = {}
    remaining = list(tickers)

    # Level 1: Tiingo (fixed endpoint — no resampleFreq/sort/limit params)
    print("[INFO] Fetching prices via Tiingo...")
    t1_prices, t1_failed = _fetch_tiingo(remaining)
    all_prices.update(t1_prices)
    remaining = sorted(t1_failed)

    if not remaining:
        print(f"[INFO] All {len(tickers)} prices from Tiingo.")
        return all_prices, set()

    print(f"[INFO] Tiingo missed {len(remaining)} tickers, trying yfinance bulk...")

    # Level 2: yfinance single bulk request
    yf_prices, yf_failed = _fetch_yfinance_bulk(remaining)
    all_prices.update(yf_prices)
    remaining = sorted(yf_failed)

    if not remaining:
        print(f"[INFO] All prices resolved (Tiingo + yfinance-bulk).")
        return all_prices, set()

    # Level 3: Alpha Vantage gap-fill (budget-limited)
    budget = min(len(remaining), _AV_PER_SESSION_BUDGET)
    if AV_KEY and budget > 0:
        to_fill = remaining[:budget]
        skipped = remaining[budget:]
        print(f"[INFO] AV gap-fill for {len(to_fill)} tickers (budget {_AV_PER_SESSION_BUDGET}/session)...")
        av_prices, av_failed = _fetch_av_quote(to_fill)
        all_prices.update(av_prices)
        remaining = sorted(av_failed) + skipped
    else:
        if not AV_KEY:
            print("[INFO] ALPHA_VANTAGE_KEY not set — skipping AV gap-fill")

    failed_final = set(remaining)
    if failed_final:
        print(f"[WARN] {len(failed_final)}/{len(tickers)} prices unavailable: {sorted(failed_final)}")
    else:
        print(f"[INFO] All {len(tickers)} prices fetched successfully.")

    return all_prices, failed_final
