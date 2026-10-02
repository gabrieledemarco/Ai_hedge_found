"""
Backfill una tantum (o periodico) dello storico prezzi/FX/benchmark/dividendi in
data/price_history.json.

Uso:  python scripts/backfill_history.py [--start 2026-06-01]

Solo additivo: non sovrascrive i punti gia' presenti. Richiede yfinance e accesso a Yahoo
Finance, quindi va lanciato in locale (da GitHub Actions Yahoo e' spesso bloccato).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from config import BENCHMARKS, FX_HISTORY_TICKERS, UNIVERSE
from price_history import update_dividends_history, update_fx_history, update_price_history


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-06-01", help="Data iniziale YYYY-MM-DD")
    args = parser.parse_args()

    tickers = list(UNIVERSE) + list(BENCHMARKS)
    added = update_price_history(tickers, args.start)
    print(f"[OK] prezzi: +{added} punti")
    added_fx = update_fx_history(FX_HISTORY_TICKERS, args.start)
    print(f"[OK] FX: +{added_fx} punti")
    added_div = update_dividends_history(list(UNIVERSE), args.start)
    print(f"[OK] dividendi: +{added_div} punti")


if __name__ == "__main__":
    main()
