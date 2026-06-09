from .base import BaseStrategy


class SentimentStrategy(BaseStrategy):
    name = "sentiment"
    min_score: float = 0.0
    min_positions: int = 5

    def compute_weights(self, universe: dict, prices: dict, signals: dict) -> dict:
        sentiment_data = signals.get("sentiment", {})

        positive = {}
        for ticker in universe:
            score = sentiment_data.get(ticker, {}).get("score", 0.0)
            if score > self.min_score:
                positive[ticker] = score + 1.0  # shift to [1, 2]

        if len(positive) < self.min_positions:
            n = len(universe)
            return {t: 1.0 / n for t in universe}

        total = sum(positive.values())
        return {t: s / total for t, s in positive.items()}
