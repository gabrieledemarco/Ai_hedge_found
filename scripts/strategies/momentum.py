from .base import BaseStrategy
from .signal_utils import has_momentum


class MomentumStrategy(BaseStrategy):
    name = "momentum"
    top_n: int = 10

    def compute_weights(self, universe: dict, prices: dict, signals: dict) -> dict:
        momentum_data = signals.get("momentum", {})

        # Solo titoli con un rendimento realmente calcolato: un segnale mancante
        # non e' "0%", e trattarlo cosi' ridurrebbe la selezione all'ordine dell'universo.
        scored = [
            (ticker, momentum_data[ticker]["return_3m"])
            for ticker in universe
            if has_momentum(momentum_data.get(ticker))
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[: self.top_n]

        if not top:
            n = len(universe)
            return {t: 1.0 / n for t in universe}

        weight = 1.0 / len(top)
        return {t: weight for t, _ in top}
