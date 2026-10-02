from .base import BaseStrategy


class InverseVolatilityStrategy(BaseStrategy):
    """Pesi proporzionali a 1/volatilita' (approccio risk-parity semplificato).

    Richiede signals["volatility"][ticker]["vol_60d"] (volatilita' annualizzata).
    Senza dati valorizzati cade su equal weight, come le altre strategie.
    """

    name = "inverse_volatility"

    def compute_weights(self, universe: dict, prices: dict, signals: dict) -> dict:
        if not universe:
            return {}
        vol_data = signals.get("volatility", {})
        inv = {}
        for ticker in universe:
            vol = vol_data.get(ticker, {}).get("vol_60d")
            if vol is not None and vol > 0:
                inv[ticker] = 1.0 / vol

        if not inv:
            n = len(universe)
            return {t: 1.0 / n for t in universe}

        total = sum(inv.values())
        return {t: w / total for t, w in inv.items()}
