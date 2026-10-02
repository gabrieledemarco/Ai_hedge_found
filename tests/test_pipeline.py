import copy

import pytest

import main_pipeline as mp
from market_note import build_template_note, generate_market_note

TWO = {
    "AAA": {"exchange": "X", "currency": "EUR", "sector": "S"},
    "BBB": {"exchange": "X", "currency": "EUR", "sector": "S"},
}


@pytest.fixture
def run(monkeypatch):
    """Esegue run_strategy_pipeline su un universo a 2 titoli, senza toccare i file."""

    def _run(
        portfolio, prices, strategy="equal_weight", failed=frozenset(), last_known=None
    ):
        monkeypatch.setattr(mp, "UNIVERSE", TWO)
        # questi test non riguardano i costi (vedi test_pipeline_costs.py)
        monkeypatch.setattr(mp, "TRANSACTION_COST_BPS", 0.0)
        monkeypatch.setattr(mp, "load_portfolio_for_strategy", lambda s: portfolio)
        monkeypatch.setattr(mp, "log_iteration_for_strategy", lambda *a, **k: None)
        return mp.run_strategy_pipeline(
            strategy, "sera", prices, {"EUR": 1.0}, {}, set(failed), last_known or {}
        )

    return _run


def _fresh(cash=1000.0, positions=None):
    return {
        "strategy": "t",
        "metadata": {"initial_capital": cash, "current_cash": cash},
        "current_positions": positions or {},
        "iterations_log": [],
    }


def test_initial_buy_uses_whole_lots(run):
    res = run(_fresh(1000.0), {"AAA": 30.0, "BBB": 70.0})
    for t in res["transactions"]:
        assert isinstance(t["shares"], int) and t["shares"] >= 1
    # target 500 EUR a testa: 16 azioni AAA @30, 7 BBB @70
    bought = {t["ticker"]: t["shares"] for t in res["transactions"]}
    assert bought == {"AAA": 16, "BBB": 7}
    assert res["portfolio"]["metadata"]["current_cash"] >= 0


def test_no_trade_when_deviation_below_threshold(run):
    pf = _fresh(
        cash=0.0,
        positions={
            "AAA": {"shares": 5, "avg_price": 100.0},  # 500 EUR
            "BBB": {"shares": 5, "avg_price": 100.0},  # 500 EUR
        },
    )
    res = run(pf, {"AAA": 102.0, "BBB": 98.0})  # scostamento ~1% < 5%
    assert res["transactions"] == []
    assert res["has_trades"] is False


def test_rebalance_sells_overweight(run):
    pf = _fresh(
        cash=0.0,
        positions={
            "AAA": {"shares": 9, "avg_price": 100.0},
            "BBB": {"shares": 1, "avg_price": 100.0},
        },
    )
    res = run(pf, {"AAA": 100.0, "BBB": 100.0})
    actions = {(t["action"], t["ticker"]) for t in res["transactions"]}
    assert ("SELL", "AAA") in actions
    assert ("BUY", "BBB") in actions


def test_cash_never_goes_negative(run):
    res = run(_fresh(50.0), {"AAA": 40.0, "BBB": 30.0})
    assert res["portfolio"]["metadata"]["current_cash"] >= 0


def test_all_prices_failed_disables_trading(run):
    res = run(_fresh(1000.0), {"AAA": 100.0, "BBB": 100.0}, failed={"AAA", "BBB"})
    assert res["transactions"] == []
    assert res["has_trades"] is False


def _held(cash=0.0):
    return _fresh(
        cash=cash,
        positions={
            "AAA": {"shares": 10, "avg_price": 100.0},
            "BBB": {"shares": 10, "avg_price": 50.0},
        },
    )


def test_total_value_keeps_positions_with_missing_price_at_last_known(run):
    """Regressione: a fine sessione i titoli senza prezzo venivano valutati 0 EUR."""
    res = run(
        _held(),
        {"AAA": 100.0},  # BBB senza prezzo
        failed={"BBB"},
        last_known={"BBB": 80.0},
    )
    assert res["total_value_eur"] == pytest.approx(1000.0 + 800.0)


def test_total_value_falls_back_to_avg_price_without_history(run):
    res = run(_held(), {"AAA": 100.0}, failed={"BBB"}, last_known={})
    assert res["total_value_eur"] == pytest.approx(1000.0 + 500.0)


def test_total_value_same_whether_or_not_prices_missing(run):
    full = run(_held(), {"AAA": 100.0, "BBB": 80.0})
    missing = run(_held(), {"AAA": 100.0}, failed={"BBB"}, last_known={"BBB": 80.0})
    assert missing["total_value_eur"] == pytest.approx(full["total_value_eur"])


def _result(total, cash, txs=()):
    return {
        "total_value_eur": total,
        "cash_eur": cash,
        "transactions": list(txs),
        "portfolio": {
            "metadata": {"initial_capital": 3000.0, "current_cash": cash},
            "current_positions": {},
        },
        "has_trades": bool(txs),
    }


def test_market_note_is_deterministic_and_mentions_best_worst():
    results = {
        "equal_weight": _result(3300.0, 100.0),
        "momentum": _result(2900.0, 800.0),
    }
    sig = {"momentum": {"AAPL": {"return_3m": 0.25}}}
    a = build_template_note(results, sig)
    assert a == build_template_note(copy.deepcopy(results), sig)
    assert "Migliore: Equal Weight (+10.0%)" in a
    assert "Peggiore: Momentum (-3.3%)" in a
    assert "AAPL" in a
    assert "Cassa oltre il 20%" in a


def test_market_note_without_llm_env_makes_no_network_call(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    def boom(*a, **k):
        raise AssertionError("rete usata senza LLM configurato")

    monkeypatch.setattr("market_note.requests.post", boom)
    assert generate_market_note({"equal_weight": _result(3000.0, 0.0)}, {})


def test_market_note_falls_back_to_template_on_llm_error(monkeypatch):
    import requests

    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1/v1")
    monkeypatch.setenv("LLM_MODEL", "x")

    def fail(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("market_note.requests.post", fail)
    results = {"equal_weight": _result(3000.0, 0.0)}
    assert generate_market_note(results, {}) == build_template_note(results, {})


def test_telegram_report_contains_note():
    results = {"equal_weight": _result(3100.0, 50.0)}
    text = mp.build_telegram_report(
        "sera", results, results["equal_weight"]["portfolio"], {"AAPL": 1.0}, signals={}
    )
    assert "NOTA DI MERCATO" in text
