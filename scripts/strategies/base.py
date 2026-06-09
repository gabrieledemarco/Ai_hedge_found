from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    name: str = "base"

    @abstractmethod
    def compute_weights(
        self,
        universe: dict,
        prices: dict,
        signals: dict,
    ) -> dict:
        """Returns normalized weights {ticker: 0.0-1.0}, sum = 1.0"""
        raise NotImplementedError
