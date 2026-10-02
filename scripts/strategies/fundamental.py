from .base import BaseStrategy
from .signal_utils import has_fundamental

# Tickers con fondamentali storicamente solidi usati come fallback
# quando signals.json non è ancora disponibile. Diverso da equal_weight
# (20 titoli) per garantire differenziazione anche senza dati.
_FUNDAMENTAL_FALLBACK = [
    "KO", "JNJ", "V", "MSFT", "AAPL",
    "ISP.MI", "ENI.MI", "ULVR.L", "GSK.L", "ENEL.MI",
]


class FundamentalStrategy(BaseStrategy):
    name = "fundamental"
    min_score: float = 0.3

    def compute_weights(self, universe: dict, prices: dict, signals: dict) -> dict:
        fundamentals = signals.get("fundamentals", {})
        has_real_data = any(has_fundamental(fundamentals.get(t)) for t in universe)

        if not has_real_data:
            # Fallback: equal weight su selezione quality pre-definita
            valid = [t for t in _FUNDAMENTAL_FALLBACK if t in universe]
            if not valid:
                valid = list(universe.keys())
            return {t: 1.0 / len(valid) for t in valid}

        raw = {}
        for ticker in universe:
            entry = fundamentals.get(ticker)
            if has_fundamental(entry) and entry["f_score"] >= self.min_score:
                raw[ticker] = entry["f_score"]

        if not raw:
            return {t: 1.0 / len(universe) for t in universe}

        total = sum(raw.values())
        return {t: s / total for t, s in raw.items()}
