import argparse
import os
import json
import time
from datetime import datetime, timezone

import yfinance as yf


def _score_and_count(info: dict) -> tuple[float | None, int]:
    """F-score normalizzato 0-1 e numero di metriche usate (None, 0 se nessuna)."""
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

    # Nessuna metrica disponibile (es. Yahoo blocca l'IP di GitHub Actions e
    # `info` torna vuoto): None, non 0.5, altrimenti sembra un dato reale.
    return (round(score / count, 4) if count > 0 else None), count


def score_fundamental(info: dict) -> float | None:
    """
    Calcola F-score normalizzato 0-1 da metriche yfinance.
    Criteri: basso PE, alto ROE, positivo FCF, basso D/E.
    """
    return _score_and_count(info)[0]


def _entry_from_info(info: dict, source: str, now: datetime) -> dict | None:
    f_score, count = _score_and_count(info)
    if f_score is None:
        return None
    return {
        "pe_ratio": info.get("trailingPE"),
        "pb_ratio": info.get("priceToBook"),
        "roe": info.get("returnOnEquity"),
        "debt_to_equity": info.get("debtToEquity"),
        "market_cap": info.get("marketCap"),
        "revenue_growth": info.get("revenueGrowth"),
        "f_score": f_score,
        "metrics_used": count,
        "source": source,
        "fetched_at": now.isoformat(),
    }


def fetch_all_fundamentals(
    universe: dict,
    previous: dict | None = None,
    av_key: str = "",
    av_budget: int = 5,
    max_age_days: int = 14,
    force: bool = False,
    now: datetime | None = None,
    sleep=time.sleep,
) -> dict:
    """Fondamentali per tutto l'universo, con cache e fallback.

    I titoli con un dato reale recente (`fetched_at` < max_age_days) non vengono richiesti
    di nuovo. Gli altri: prima Yahoo, poi (se c'e' la chiave e resta quota) Alpha Vantage.
    Un titolo senza alcuna fonte riceve {"error": ...}: il chiamante non deve usarlo per
    sovrascrivere un dato reale precedente (vedi signals_utils.merge_fundamentals).
    """
    from fundamentals_sources import (
        QuotaExceeded,
        fetch_alpha_vantage_overview,
        plan_refresh,
    )

    previous = previous or {}
    now = now or datetime.now(timezone.utc)
    results = {t: previous[t] for t in universe if t in previous}
    due = plan_refresh(universe, previous, now, max_age_days, force)
    print(
        f"[INFO] Fundamentals: {len(due)}/{len(universe)} tickers to refresh "
        f"(max age {max_age_days}d, Alpha Vantage budget {av_budget if av_key else 0})."
    )

    av_calls = 0
    av_dead = False
    for i, ticker in enumerate(due):
        print(f"  [{i+1}/{len(due)}] {ticker}...")
        entry, error = None, "no_data"
        try:
            entry = _entry_from_info(yf.Ticker(ticker).info, "yfinance", now)
        except Exception as e:
            error = str(e)[:120]
            print(f"[WARN] Yahoo failed for {ticker}: {e}")
        time.sleep(0.5)

        if entry is None and av_key and not av_dead and av_calls < av_budget:
            if av_calls:
                sleep(13)  # piano gratuito: 5 richieste/minuto
            av_calls += 1
            try:
                info = fetch_alpha_vantage_overview(ticker, av_key)
                entry = _entry_from_info(info, "alpha_vantage", now) if info else None
            except QuotaExceeded as e:
                av_dead = True
                error = f"av_quota: {e}"
                print(f"[WARN] Alpha Vantage quota exhausted: {e}")
            except Exception as e:
                error = str(e)[:120]
                print(f"[WARN] Alpha Vantage failed for {ticker}: {e}")

        if entry is not None:
            results[ticker] = entry
        else:
            print(f"[WARN] No fundamentals data for {ticker}")
            # un errore non cancella un dato reale precedente: lo gestisce il chiamante
            results[ticker] = {"error": error}

    return results


def fetch_momentum(universe: dict, fallback: dict | None = None) -> dict:
    """Momentum 3m e 1m per ogni ticker.

    Prima prova yfinance; se non risponde (succede su GitHub Actions) usa
    `fallback` (segnali calcolati dallo storico prezzi del progetto). Un ticker
    senza alcun dato viene omesso: mai riempito con 0.0.
    """
    fallback = fallback or {}
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
                    "source": "yfinance",
                }
                continue
        except Exception as e:
            print(f"[WARN] Momentum failed for {ticker}: {e}")
        if ticker in fallback:
            results[ticker] = fallback[ticker]
        else:
            print(f"[WARN] No momentum data for {ticker}: omitted")

    return results


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(__file__))
    from config import UNIVERSE

    from fundamentals_sources import (
        DEFAULT_MAX_AGE_DAYS,
        av_budget_from_env,
    )
    from price_history import combined_history, compute_price_signals
    from signals_utils import merge_fundamentals
    from strategies.signal_utils import has_fundamental

    parser = argparse.ArgumentParser(description="Aggiorna fondamentali e momentum in data/signals.json")
    parser.add_argument("--force", action="store_true", help="riscarica anche i dati ancora freschi")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    args = parser.parse_args()

    signals_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "signals.json"
    )
    try:
        with open(signals_path) as f:
            signals = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        signals = {}
    previous = signals.get("fundamentals", {})

    price_signals = compute_price_signals(combined_history())
    fundamentals = fetch_all_fundamentals(
        UNIVERSE,
        previous=previous,
        av_key=os.environ.get("ALPHA_VANTAGE_KEY", ""),
        av_budget=av_budget_from_env(),
        max_age_days=args.max_age_days,
        force=args.force,
    )
    momentum = fetch_momentum(UNIVERSE, fallback=price_signals["momentum"])

    # Un fetch fallito non deve cancellare dati reali gia' presenti.
    merged = merge_fundamentals(fundamentals, previous)
    refreshed = sum(
        1
        for t, e in merged.items()
        if has_fundamental(e) and e.get("fetched_at") != (previous.get(t) or {}).get("fetched_at")
    )
    signals["fundamentals"] = merged
    signals["momentum"] = momentum
    signals["volatility"] = price_signals["volatility"]
    signals["trend"] = price_signals["trend"]
    if refreshed or "fundamentals_updated" not in signals:
        signals["fundamentals_updated"] = datetime.now(timezone.utc).isoformat()

    with open(signals_path, "w") as f:
        json.dump(signals, f, indent=2)

    real = sum(1 for e in merged.values() if has_fundamental(e))
    print(
        f"[OK] Fundamentals: {real}/{len(UNIVERSE)} real ({refreshed} refreshed). "
        f"Saved to {signals_path}"
    )
