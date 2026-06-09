from .base import BaseStrategy


class EqualWeightStrategy(BaseStrategy):
    name = "equal_weight"

    def compute_weights(self, universe: dict, prices: dict, signals: dict) -> dict:
        n = len(universe)
        if n == 0:
            return {}
        return {t: 1.0 / n for t in universe}
