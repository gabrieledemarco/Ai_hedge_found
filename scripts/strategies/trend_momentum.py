from .base import BaseStrategy
from .signal_utils import has_momentum


class TrendMomentumStrategy(BaseStrategy):
    """Momentum con filtro di trend: top-N per rendimento a 3 mesi, ma solo tra
    i titoli sopra la media mobile a 200 giorni.

    Richiede signals["momentum"][t]["return_3m"] e signals["trend"][t]["above_ma200"].
    Se nessun titolo passa il filtro il portafoglio resta in cassa ({}), che e'
    il punto del filtro: ridurre i drawdown nei mercati ribassisti.
    Senza dati di trend (signals["trend"] assente o vuoto, es. meno di 200 giorni
    di storico) il filtro e' disattivato.
    """

    name = "trend_momentum"
    top_n: int = 10

    def compute_weights(self, universe: dict, prices: dict, signals: dict) -> dict:
        momentum_data = signals.get("momentum", {})
        trend_data = signals.get("trend")

        if not any(has_momentum(momentum_data.get(t)) for t in universe):
            # nessun dato di momentum: fallback equal weight come le altre strategie
            n = len(universe)
            return {t: 1.0 / n for t in universe} if n else {}

        scored = []
        for ticker in universe:
            if trend_data and not trend_data.get(ticker, {}).get(
                "above_ma200", False
            ):
                continue
            if has_momentum(momentum_data.get(ticker)):
                scored.append((ticker, momentum_data[ticker]["return_3m"]))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[: self.top_n]
        if not top:
            return {}
        return {t: 1.0 / len(top) for t, _ in top}
