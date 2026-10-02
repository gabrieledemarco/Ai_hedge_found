"""Costi di transazione simulati e campi aggiuntivi nel log della pipeline."""
import pytest

import main_pipeline as mp

UNIVERSE = {
    "AAA": {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "BBB.MI": {"exchange": "BIT", "currency": "EUR", "sector": "Energy"},
}
FX = {"USD": 0.5, "EUR": 1.0}


@pytest.fixture
def run(monkeypatch):
    """Esegue run_strategy_pipeline mantenendo il portafoglio tra una sessione e l'altra,
    senza toccare i file."""
    state = {
        "strategy": "t",
        "metadata": {"initial_capital": 3000.0, "current_cash": 3000.0},
        "current_positions": {},
        "iterations_log": [],
    }
    monkeypatch.setattr(mp, "UNIVERSE", UNIVERSE)
    monkeypatch.setattr(mp, "TRANSACTION_COST_BPS", 100.0)  # 1% per rendere i costi visibili
    monkeypatch.setattr(mp, "load_portfolio_for_strategy", lambda s: state)
    logged = []

    def fake_log(name, portfolio, session, total, txns, prices, reasoning, **kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(mp, "log_iteration_for_strategy", fake_log)

    def _run(prices, failed=frozenset(), last_known=None):
        return mp.run_strategy_pipeline(
            "equal_weight", "mattina", prices, FX, {}, set(failed), last_known or {}
        )

    _run.logged = logged
    return _run


def test_first_run_buys_and_charges_fees(run):
    r = run({"AAA": 100.0, "BBB.MI": 50.0})
    assert r["has_trades"]
    fees = sum(t["fee_eur"] for t in r["transactions"])
    assert fees > 0
    p = r["portfolio"]
    assert p["metadata"]["current_cash"] >= 0
    assert p["metadata"]["fees_paid"] == pytest.approx(fees, abs=1e-3)
    # il totale e' il capitale iniziale meno i costi (prezzi invariati), a meno di arrotondamenti
    assert r["total_value_eur"] == pytest.approx(3000.0 - fees, abs=1.0)


def test_buy_never_exceeds_cash_including_fee(run):
    r = run({"AAA": 100.0, "BBB.MI": 50.0})
    spent = sum(t["total_cost_eur"] + t["fee_eur"] for t in r["transactions"] if t["action"] == "BUY")
    assert spent <= 3000.0 + 1e-6


def test_log_records_stale_tickers_and_fees(run):
    run({"AAA": 100.0}, failed={"BBB.MI"})
    extra = run.logged[-1]["extra"]
    assert extra["stale_tickers"] == ["BBB.MI"]
    assert extra["fees_eur"] >= 0
    assert run.logged[-1]["fx_rates"] == FX


def test_stale_ticker_keeps_value_through_a_second_session(run):
    first = run({"AAA": 100.0, "BBB.MI": 50.0})
    second = run({"AAA": 100.0}, failed={"BBB.MI"}, last_known={"BBB.MI": 50.0})
    assert second["total_value_eur"] == pytest.approx(first["total_value_eur"], rel=0.01)
