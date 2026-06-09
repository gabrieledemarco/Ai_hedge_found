from .base import BaseStrategy


class MomentumStrategy(BaseStrategy):
    name = "momentum"
    top_n: int = 10

    def compute_weights(self, universe: dict, prices: dict, signals: dict) -> dict:
        momentum_data = signals.get("momentum", {})

        scored = []
        for ticker in universe:
            ret_3m = momentum_data.get(ticker, {}).get("return_3m", 0.0)
            scored.append((ticker, ret_3m))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[: self.top_n]

        if not top:
            n = len(universe)
            return {t: 1.0 / n for t in universe}

        weight = 1.0 / len(top)
        return {t: weight for t, _ in top}
