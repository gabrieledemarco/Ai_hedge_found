"""Serie di equity datate e metriche della dashboard statica (metrics.py, parte 2)."""
import pytest

from metrics import (
    build_equity_series,
    compute_metrics,
    daily_series,
    daily_series_with_dividends,
    drawdown_series,
    max_drawdown_dated,
    rebase,
    relative_metrics,
)

UNIVERSE = {
    "AAA": {"currency": "USD"},
    "BBB.MI": {"currency": "EUR"},
}


def test_max_drawdown_and_dates():
    daily = [("2026-01-01", 100), ("2026-01-02", 120), ("2026-01-03", 90), ("2026-01-04", 130)]
    mdd, peak, trough = max_drawdown_dated(daily)
    assert mdd == pytest.approx(0.25)
    assert (peak, trough) == ("2026-01-02", "2026-01-03")
    assert drawdown_series(daily)[-1][1] == 0.0


def test_daily_series_keeps_last_value_of_each_day():
    # 3 rilevazioni al giorno non devono creare 3 rendimenti al giorno
    series = [
        {"date": "2026-01-01", "value": 100.0},
        {"date": "2026-01-01", "value": 100.0},
        {"date": "2026-01-01", "value": 101.0},
        {"date": "2026-01-02", "value": 102.0},
        {"date": "2026-01-02", "value": 102.0},
        {"date": "2026-01-02", "value": 103.02},
    ]
    daily = daily_series(series)
    assert daily == [("2026-01-01", 101.0), ("2026-01-02", 103.02)]
    m = compute_metrics(daily)
    assert m["total_return"] == pytest.approx(0.02)
    assert m["n_days"] == 2


def test_compute_metrics_handles_short_and_flat_series():
    assert compute_metrics([])["total_return"] == 0.0
    flat = [("2026-01-01", 100.0), ("2026-01-02", 100.0), ("2026-01-03", 100.0)]
    m = compute_metrics(flat, risk_free=0.02)
    assert m["sharpe"] == 0.0 and m["max_drawdown"] == 0.0


def test_risk_free_lowers_sharpe():
    values = [100, 101, 100.5, 102, 103]
    daily = [(f"2026-01-{d:02d}", v) for d, v in enumerate(values, start=1)]
    assert compute_metrics(daily, risk_free=0.05)["sharpe"] < compute_metrics(daily)["sharpe"]


def test_annualization_is_compound_over_calendar_days():
    daily = [("2026-01-01", 100.0), ("2026-01-02", 100.0), ("2026-04-02", 110.0)]
    m = compute_metrics(daily)
    assert m["ann_return"] == pytest.approx(1.10 ** (365 / 91) - 1)


def test_rebase():
    assert rebase([("a", 50.0), ("b", 75.0)]) == [("a", 100.0), ("b", 150.0)]


def _entry(day, cash, positions, prices, total, fx=None):
    e = {
        "timestamp": f"{day}T12:00:00+00:00",
        "current_cash": cash,
        "positions": positions,
        "prices_used": prices,
        "total_value_eur": total,
    }
    if fx:
        e["fx_rates"] = fx
    return e


def test_equity_series_values_missing_prices_instead_of_zero():
    # Regressione: titolo senza prezzo contato 0 EUR -> falso crollo dell'equity.
    positions = {"AAA": {"shares": 1, "avg_price": 9}, "BBB.MI": {"shares": 10, "avg_price": 5}}
    history = [
        _entry("2026-03-02", 100, positions, {"AAA": 10.0, "BBB.MI": 5.0}, 159.0, {"USD": 0.9}),
        # BBB.MI senza prezzo: il totale registrato perde 50 EUR
        _entry("2026-03-03", 100, positions, {"AAA": 10.0}, 109.0, {"USD": 0.9}),
    ]
    price_history = {"BBB.MI": {"2026-03-02": 5.0, "2026-03-03": 6.0}}
    series = build_equity_series(history, price_history, UNIVERSE, {"USD": 0.5, "EUR": 1.0})
    assert series[0]["value"] == pytest.approx(159.0)
    assert series[1]["value"] == pytest.approx(100 + 9 + 60)
    assert series[1]["repaired"] is True and series[0]["repaired"] is False


def test_equity_series_uses_historical_fx_not_static_fallback():
    positions = {"AAA": {"shares": 2, "avg_price": 9}}
    # totale registrato col fallback 0.92, ma il cambio storico del giorno e' 0.80
    history = [_entry("2026-03-02", 0, positions, {"AAA": 100.0}, 2 * 100 * 0.92)]
    ph = {"FX:USD": {"2026-03-02": 0.80}}
    series = build_equity_series(history, ph, UNIVERSE, {"USD": 0.92, "EUR": 1.0})
    assert series[0]["value"] == pytest.approx(160.0)


# ── Dividendi stimati ────────────────────────────────────────────────────────

def _held(day, shares):
    return _entry(day, 0, {"AAA": {"shares": shares, "avg_price": 9}} if shares else {}, {"AAA": 10.0}, 0.0)


def test_dividends_are_counted_once_from_the_next_entry_with_fx():
    history = [_held("2026-03-02", 10), _held("2026-03-03", 10), _held("2026-03-04", 10)]
    dividends = {"AAA": {"2026-03-03": 1.0, "2026-02-01": 9.0}}  # il secondo precede l'inizio
    ph = {"FX:USD": {"2026-03-03": 0.5}}
    series = build_equity_series(history, ph, UNIVERSE, {"USD": 0.9, "EUR": 1.0}, dividends)
    assert [p["div_cum"] for p in series] == [0.0, 5.0, 5.0]  # 10 azioni x 1 USD x 0.5


def test_no_dividend_for_shares_bought_after_the_ex_date():
    history = [_held("2026-03-02", 0), _held("2026-03-03", 10)]  # comprate DOPO l'ex-date del 03/03
    series = build_equity_series(history, {}, UNIVERSE, {"USD": 0.9, "EUR": 1.0}, {"AAA": {"2026-03-03": 1.0}})
    assert series[-1]["div_cum"] == 0.0


def test_daily_series_with_dividends_adds_cumulative_estimate():
    series = [
        {"date": "2026-03-02", "value": 100.0, "div_cum": 0.0},
        {"date": "2026-03-03", "value": 101.0, "div_cum": 2.5},
        {"date": "2026-03-03", "value": 102.0, "div_cum": 2.5},
    ]
    assert daily_series_with_dividends(series) == [("2026-03-02", 100.0), ("2026-03-03", 104.5)]


# ── Metriche rispetto al benchmark ───────────────────────────────────────────

def _dated(values):
    from datetime import date, timedelta

    start = date(2026, 1, 1)
    return [((start + timedelta(days=i)).isoformat(), v) for i, v in enumerate(values)]


def _from_returns(rets, base=100.0):
    vals = [base]
    for r in rets:
        vals.append(vals[-1] * (1 + r))
    return _dated(vals)


BENCH_RETS = [0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.005, 0.012, -0.015, 0.008] * 3


def test_relative_metrics_for_half_exposure_strategy():
    bench = _from_returns(BENCH_RETS)
    strat = _from_returns([0.5 * r for r in BENCH_RETS])
    m = relative_metrics(strat, bench)
    assert m["beta"] == pytest.approx(0.5, abs=1e-9)
    assert m["correlation"] == pytest.approx(1.0, abs=1e-9)
    assert m["up_capture"] == pytest.approx(0.5, abs=1e-9)
    assert m["down_capture"] == pytest.approx(0.5, abs=1e-9)
    assert m["alpha"] == pytest.approx(0.0, abs=1e-9)  # nessun risk-free: puro beta, nessun alpha


def test_relative_metrics_identical_series_has_zero_tracking_error():
    bench = _from_returns(BENCH_RETS)
    m = relative_metrics(bench, bench)
    assert m["beta"] == pytest.approx(1.0) and m["tracking_error"] == pytest.approx(0.0, abs=1e-12)
    assert m["information_ratio"] is None  # indefinito con tracking error nullo


def test_relative_metrics_detects_positive_alpha_and_information_ratio():
    bench = _from_returns(BENCH_RETS)
    # extra-rendimento variabile con media +10 bps/giorno (costante = tracking error nullo)
    extra = [0.002, 0.0] * (len(BENCH_RETS) // 2)
    strat = _from_returns([r + e for r, e in zip(BENCH_RETS, extra)])
    m = relative_metrics(strat, bench)
    assert m["alpha"] > 0.2 and m["information_ratio"] > 1


def test_relative_metrics_needs_enough_common_dates():
    bench = _from_returns(BENCH_RETS[:5])
    assert relative_metrics(bench, bench) is None
    # date non in comune: nessuna osservazione utile
    a = _dated([100.0 + i for i in range(40)])
    b = [("2027-01-%02d" % (i + 1), 100.0 + i) for i in range(28)]
    assert relative_metrics(a, b) is None
