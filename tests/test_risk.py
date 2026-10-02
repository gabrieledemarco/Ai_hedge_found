import pytest

import backtest
from config import UNIVERSE
from strategies import (
    EqualWeightStrategy,
    MomentumStrategy,
    RiskManagedStrategy,
    cap_weights,
)


def test_no_caps_leaves_weights_unchanged():
    w = {"A": 0.5, "B": 0.3, "C": 0.2}
    assert cap_weights(w, {"A": "x", "B": "y", "C": "z"}) == pytest.approx(w)


def test_max_weight_redistributes_excess():
    w = {"A": 0.7, "B": 0.2, "C": 0.1}
    out = cap_weights(w, {}, max_weight=0.4)
    assert out["A"] == pytest.approx(0.4)
    assert sum(out.values()) == pytest.approx(1.0)
    assert out["B"] > 0.2 and out["C"] > 0.1


def test_sector_cap_enforced_and_total_preserved_when_room_exists():
    sectors = {"A": "tech", "B": "tech", "C": "fin", "D": "en", "E": "util"}
    w = {"A": 0.3, "B": 0.3, "C": 0.2, "D": 0.1, "E": 0.1}
    out = cap_weights(w, sectors, max_weight=1.0, sector_cap=0.4)
    assert out["A"] + out["B"] <= 0.4 + 1e-9
    assert sum(out.values()) == pytest.approx(1.0)


def test_infeasible_caps_leave_cash_instead_of_breaking_them():
    # 2 titoli, tetto 30% ciascuno: al massimo 60% investito
    out = cap_weights({"A": 0.5, "B": 0.5}, {}, max_weight=0.3)
    assert out == pytest.approx({"A": 0.3, "B": 0.3})
    assert sum(out.values()) < 1.0


def test_never_exceeds_caps_even_with_chained_redistribution():
    sectors = {t: ("tech" if i < 6 else "other") for i, t in enumerate("ABCDEFGHIJ")}
    w = {t: (0.4 if i == 0 else 0.6 / 9) for i, t in enumerate("ABCDEFGHIJ")}
    out = cap_weights(w, sectors, max_weight=0.2, sector_cap=0.35)
    assert all(x <= 0.2 + 1e-9 for x in out.values())
    tech = sum(x for t, x in out.items() if sectors[t] == "tech")
    assert tech <= 0.35 + 1e-9


def test_empty_and_zero_weights():
    assert cap_weights({}, {}) == {}
    assert cap_weights({"A": 0.0}, {}) == {}


def test_wrapper_applies_caps_on_real_universe():
    sig = {
        "momentum": {
            t: {"return_3m": 0.5 if info["sector"] == "Tech" else 0.01, "return_1m": 0.01}
            for t, info in UNIVERSE.items()
        }
    }
    raw = MomentumStrategy().compute_weights(UNIVERSE, {}, sig)
    tech_raw = sum(w for t, w in raw.items() if UNIVERSE[t]["sector"] == "Tech")
    assert tech_raw > 0.35  # il caso che il livello deve correggere

    managed = RiskManagedStrategy(MomentumStrategy())
    out = managed.compute_weights(UNIVERSE, {}, sig)
    tech = sum(w for t, w in out.items() if UNIVERSE[t]["sector"] == "Tech")
    assert tech <= 0.35 + 1e-9
    assert max(out.values()) <= 0.15 + 1e-9
    assert managed.name == "momentum_risk"


def test_wrapper_is_a_noop_on_balanced_equal_weight():
    inner = EqualWeightStrategy()
    uni = {f"T{i}": {"sector": f"S{i % 10}"} for i in range(20)}
    out = RiskManagedStrategy(inner).compute_weights(uni, {}, {})
    assert out == pytest.approx(inner.compute_weights(uni, {}, {}))


def test_subperiod_metrics_cover_whole_curve():
    import numpy as np
    import pandas as pd

    idx = pd.bdate_range("2023-01-02", periods=400)
    curves = {
        "a": pd.Series(3000 * np.cumprod(1 + np.full(400, 0.0005)), index=idx),
        # benchmark con calendario diverso (meno giorni)
        "bench": pd.Series(3000 * np.cumprod(1 + np.full(300, 0.0003)), index=idx[:300]),
    }
    subs = backtest.subperiod_metrics(curves, splits=2)
    assert len(subs) == 2
    assert subs[0]["end"] <= subs[1]["start"] or subs[0]["end"] == subs[1]["start"]
    assert subs[0]["metrics"]["a"]["total_return"] > 0
    md = backtest.format_markdown(
        {n: backtest.summarize(s.tolist()) for n, s in curves.items()},
        {"start": "x", "end": "y", "initial": 3000, "rebalance_every": 21, "cost_bps": 10},
        subs,
    )
    assert "Stabilità per sottoperiodo" in md


def test_default_strategies_include_risk_variant():
    assert "momentum_risk" in backtest.default_strategies()
