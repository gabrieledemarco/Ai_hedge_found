"""Controlli di rischio come livello sopra una strategia qualsiasi.

`RiskManagedStrategy(inner)` prende i pesi della strategia interna e applica:
- un tetto per singolo titolo (`max_weight`);
- un tetto per settore (`sector_cap`).

L'eccesso viene redistribuito sui titoli che hanno ancora spazio; se non ce n'e'
abbastanza, il resto resta in cassa (pesi con somma < 1). E' una scelta voluta:
meglio cassa che concentrazione oltre soglia.
"""
from .base import BaseStrategy

_EPS = 1e-9


def cap_weights(
    weights: dict[str, float],
    sectors: dict[str, str],
    max_weight: float = 1.0,
    sector_cap: float = 1.0,
    max_iter: int = 50,
) -> dict[str, float]:
    """Applica tetti per titolo e per settore, redistribuendo l'eccesso."""
    w = {t: x for t, x in weights.items() if x > 0}
    if not w:
        return {}

    def sector_of(t):
        return sectors.get(t, t)  # senza settore: gruppo a se'

    for _ in range(max_iter):
        # 1. tetto per titolo
        excess = 0.0
        for t in w:
            if w[t] > max_weight + _EPS:
                excess += w[t] - max_weight
                w[t] = max_weight
        # 2. tetto per settore: riduzione proporzionale dentro il settore
        totals: dict[str, float] = {}
        for t, x in w.items():
            totals[sector_of(t)] = totals.get(sector_of(t), 0.0) + x
        for sec, tot in totals.items():
            if tot > sector_cap + _EPS:
                scale = sector_cap / tot
                for t in w:
                    if sector_of(t) == sec:
                        excess += w[t] * (1 - scale)
                        w[t] *= scale
        if excess <= _EPS:
            break
        # 3. redistribuzione sui titoli con spazio (titolo e settore sotto tetto)
        totals = {}
        for t, x in w.items():
            totals[sector_of(t)] = totals.get(sector_of(t), 0.0) + x
        receivers = {
            t: x
            for t, x in w.items()
            if x < max_weight - _EPS and totals[sector_of(t)] < sector_cap - _EPS
        }
        if not receivers:
            break  # niente spazio: l'eccesso resta in cassa
        base = sum(receivers.values())
        for t, x in receivers.items():
            w[t] += excess * x / base
    return {t: x for t, x in w.items() if x > _EPS}


class RiskManagedStrategy(BaseStrategy):
    def __init__(
        self,
        inner: BaseStrategy,
        sector_cap: float = 0.35,
        max_weight: float = 0.15,
    ):
        self.inner = inner
        self.sector_cap = sector_cap
        self.max_weight = max_weight
        self.name = f"{inner.name}_risk"

    def compute_weights(self, universe: dict, prices: dict, signals: dict) -> dict:
        raw = self.inner.compute_weights(universe, prices, signals)
        sectors = {t: info.get("sector", t) for t, info in universe.items()}
        return cap_weights(raw, sectors, self.max_weight, self.sector_cap)
