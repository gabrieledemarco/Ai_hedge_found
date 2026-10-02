"""Ripara i `total_value_eur` gia' registrati quando mancavano dei prezzi.

Fino alla correzione in `valuation.py`, le sessioni con prezzi mancanti
valutavano a 0 EUR le posizioni senza prezzo, creando buchi nella equity curve.
Per ogni iterazione colpita si aggiunge il valore di quelle posizioni all'ultimo
prezzo reale noto *fino a quel giorno* (nessun look-ahead).

Precisione: esatta per i titoli in EUR (cambio 1.0); per USD/GBP si usa il
cambio di ripiego di config.FX_FALLBACK, quindi e' un'approssimazione. Le voci
corrette ricevono "value_repaired": true.

Uso (di default NON scrive nulla):
    python scripts/repair_history.py            # anteprima
    python scripts/repair_history.py --apply    # riscrive i file in data/portfolios/
"""
import argparse
import bisect
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from config import FX_FALLBACK, UNIVERSE  # noqa: E402
from price_history import PORTFOLIOS_DIR, load_history  # noqa: E402

ALL_FAILED_MARK = "tutti i prezzi sono fallback"


def repair_log(log: list[dict], history: dict) -> list[dict]:
    """Ritorna l'elenco delle correzioni [{index, day, delta}] e modifica `log`."""
    days = {t: [d for d, _ in s] for t, s in history.items()}
    changes = []
    for i, entry in enumerate(log):
        prices = entry.get("prices_used") or {}
        if not prices or ALL_FAILED_MARK in entry.get("reasoning", ""):
            continue
        day = entry.get("timestamp", "")[:10]
        delta = 0.0
        for ticker, pos in (entry.get("positions") or {}).items():
            if prices.get(ticker) or ticker not in UNIVERSE:
                continue
            series = history.get(ticker)
            if not series:
                continue
            idx = bisect.bisect_right(days[ticker], day) - 1
            if idx < 0:
                continue
            fx = FX_FALLBACK.get(UNIVERSE[ticker]["currency"], 1.0)
            delta += pos["shares"] * series[idx][1] * fx
        if delta > 0:
            entry["total_value_eur"] = round(entry["total_value_eur"] + delta, 2)
            entry["value_repaired"] = True
            changes.append({"index": i, "day": day, "delta": round(delta, 2)})
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="scrive i file")
    parser.add_argument("--dir", default=PORTFOLIOS_DIR)
    args = parser.parse_args()

    history = load_history(args.dir)
    for path in sorted(glob.glob(os.path.join(args.dir, "*.json"))):
        with open(path) as f:
            data = json.load(f)
        changes = repair_log(data.get("iterations_log", []), history)
        name = os.path.basename(path)
        if not changes:
            print(f"{name}: nessuna correzione")
            continue
        worst = max(changes, key=lambda c: c["delta"])
        print(
            f"{name}: {len(changes)} voci da correggere "
            f"(max +{worst['delta']:.2f} EUR il {worst['day']})"
        )
        if args.apply:
            with open(path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
    if not args.apply:
        print("\nAnteprima: nessun file modificato. Usa --apply per scrivere.")


if __name__ == "__main__":
    main()
