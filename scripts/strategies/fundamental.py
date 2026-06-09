from .base import BaseStrategy


class FundamentalStrategy(BaseStrategy):
    name = "fundamental"
    min_score: float = 0.3

    def compute_weights(self, universe: dict, prices: dict, signals: dict) -> dict:
        fundamentals = signals.get("fundamentals", {})

        raw = {}
        for ticker in universe:
            f_score = fundamentals.get(ticker, {}).get("f_score", 0.5)
            if f_score >= self.min_score:
                raw[ticker] = f_score

        if not raw:
            n = len(universe)
            return {t: 1.0 / n for t in universe}

        total = sum(raw.values())
        return {t: s / total for t, s in raw.items()}
