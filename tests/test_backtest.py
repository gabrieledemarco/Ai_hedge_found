import numpy as np
import pandas as pd
import pytest

import backtest
from strategies import EqualWeightStrategy, TrendMomentumStrategy


def _prices(n=400, drifts=(0.0005, 0.0, -0.0003), seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    cols = {}
    for name, d in zip("ABC", drifts):
        cols[name] = 100 * np.cumprod(1 + d + rng.normal(0, 0.01, n))
    return pd.DataFrame(cols, index=idx)


def test_build_signals_uses_only_given_history():
    px = _prices()
    sig_full = backtest.build_signals(px)
    sig_cut = backtest.build_signals(px.iloc[:300])
    assert sig_full["momentum"]["A"]["return_3m"] != sig_cut["momentum"]["A"]["return_3m"]
    expected = px["A"].iloc[299] / px["A"].iloc[299 - 63] - 1
    assert sig_cut["momentum"]["A"]["return_3m"] == pytest.approx(expected)


def test_equal_weight_no_costs_matches_manual_rebalance():
    px = _prices()
    curves = backtest.run_backtest(
        px,
        {"eq": EqualWeightStrategy()},
        {t: {} for t in px.columns},
        rebalance_every=1,
        cost_bps=0.0,
        initial=3000.0,
    )
    eq = curves["eq"]
    assert eq.iloc[0] == pytest.approx(3000.0)
    # ribilanciamento giornaliero a pesi uguali = media dei rendimenti
    rets = px.pct_change().iloc[200:]
    expected = 3000.0 * (1 + rets.mean(axis=1).iloc[1:]).cumprod()
    assert eq.iloc[1:].to_numpy() == pytest.approx(expected.to_numpy(), rel=1e-9)


def test_costs_reduce_final_value():
    px = _prices()
    kw = dict(universe={t: {} for t in px.columns}, rebalance_every=5)
    free = backtest.run_backtest(px, {"s": EqualWeightStrategy()}, cost_bps=0, **kw)
    paid = backtest.run_backtest(px, {"s": EqualWeightStrategy()}, cost_bps=50, **kw)
    assert paid["s"].iloc[-1] < free["s"].iloc[-1]


def test_all_cash_strategy_keeps_capital():
    px = _prices(drifts=(-0.002, -0.002, -0.002))
    # trend filter con mercato in calo: tutti sotto MA200 -> cassa
    curves = backtest.run_backtest(
        px, {"t": TrendMomentumStrategy()}, {t: {} for t in px.columns}
    )
    assert curves["t"].iloc[-1] == pytest.approx(3000.0)


def test_insufficient_history_raises():
    px = _prices(n=100)
    with pytest.raises(ValueError):
        backtest.run_backtest(px, {"eq": EqualWeightStrategy()})


def test_buy_and_hold_starts_at_initial():
    px = _prices()
    s = backtest.buy_and_hold(px["A"], px.index[200], initial=3000.0)
    assert s.iloc[0] == pytest.approx(3000.0)
