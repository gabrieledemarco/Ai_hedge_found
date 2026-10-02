import math

import pytest

import metrics


def test_daily_returns():
    assert metrics.daily_returns([100, 110, 99]) == pytest.approx([0.1, -0.1])


def test_total_return_and_short_series():
    assert metrics.total_return([100, 150]) == pytest.approx(0.5)
    assert metrics.total_return([100]) == 0.0


def test_max_drawdown():
    assert metrics.max_drawdown([100, 120, 90, 130, 117]) == pytest.approx(0.25)
    assert metrics.max_drawdown([100, 110, 120]) == 0.0
    assert metrics.max_drawdown([]) == 0.0


def test_cagr_doubling_in_one_year():
    values = [100.0] + [200.0] * 252
    assert metrics.cagr(values) == pytest.approx(1.0)


def test_sharpe_zero_vol_is_zero():
    assert metrics.sharpe([0.01] * 10) == 0.0


def test_sharpe_positive_for_positive_drift():
    rets = [0.01, 0.02, -0.005, 0.015, 0.01, 0.0, 0.02]
    assert metrics.sharpe(rets) > 0


def test_sortino_ignores_upside_volatility():
    only_up = [0.01, 0.03, 0.02, 0.05]
    assert metrics.sortino(only_up) == 0.0  # nessun downside: indefinito -> 0
    mixed = [0.01, -0.02, 0.03, -0.01, 0.02]
    assert metrics.sortino(mixed) > 0


def test_annualized_vol_matches_formula():
    rets = [0.01, -0.01, 0.01, -0.01]
    mean = 0.0
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / 3)
    assert metrics.annualized_vol(rets) == pytest.approx(sd * math.sqrt(252))


def test_summarize_keys():
    s = metrics.summarize([100, 101, 99, 103, 104])
    assert set(s) == {
        "total_return", "cagr", "volatility", "sharpe",
        "sortino", "max_drawdown", "calmar",
    }
