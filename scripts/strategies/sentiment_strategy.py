from .base import BaseStrategy

# Tickers con sentiment storicamente positivo usati come fallback
# quando signals.json non è ancora disponibile.
_SENTIMENT_FALLBACK = [
    "AAPL", "NVDA", "MSFT", "GOOGL", "AMZN",
    "MONC.MI", "LDO.MI", "RIO.L", "V", "TSLA",
]


class SentimentStrategy(BaseStrategy):
    name = "sentiment"
    min_score: float = 0.0
    min_positions: int = 5

    def compute_weights(self, universe: dict, prices: dict, signals: dict) -> dict:
        sentiment_data = signals.get("sentiment", {})
        has_real_data = any(
            sentiment_data.get(t, {}).get("num_articles", 0) > 0
            for t in universe
        )

        if not has_real_data:
            # Fallback: equal weight su selezione growth pre-definita
            valid = [t for t in _SENTIMENT_FALLBACK if t in universe]
            if not valid:
                valid = list(universe.keys())
            return {t: 1.0 / len(valid) for t in valid}

        positive = {}
        for ticker in universe:
            score = sentiment_data.get(ticker, {}).get("score", 0.0)
            if score >= self.min_score:  # >= include neutrali (0.0)
                positive[ticker] = score + 1.0  # shift to [1, 2]

        if len(positive) < self.min_positions:
            valid = [t for t in _SENTIMENT_FALLBACK if t in universe]
            return {t: 1.0 / len(valid) for t in valid}

        total = sum(positive.values())
        return {t: s / total for t, s in positive.items()}
