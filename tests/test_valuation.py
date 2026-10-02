import pytest

from valuation import price_eur, value_positions_eur

UNI = {
    "US": {"currency": "USD"},
    "UK": {"currency": "GBp"},
    "IT": {"currency": "EUR"},
}
FX = {"USD": 0.9, "GBp": 0.01, "EUR": 1.0}


def _pf(cash=100.0):
    return {
        "metadata": {"current_cash": cash},
        "current_positions": {
            "US": {"shares": 2, "avg_price": 50.0},
            "UK": {"shares": 3, "avg_price": 10.0},
            "IT": {"shares": 4, "avg_price": 5.0},
        },
    }


def test_current_price_converted_with_fx():
    per, total = value_positions_eur(_pf(), UNI, {"US": 100, "UK": 2000, "IT": 6}, FX)
    assert per == {"US": pytest.approx(180.0), "UK": pytest.approx(60.0), "IT": 24.0}
    assert total == pytest.approx(180 + 60 + 24 + 100)


def test_missing_price_uses_last_known_then_avg_price():
    last = {"UK": 1000.0}
    per, _ = value_positions_eur(_pf(), UNI, {"US": 100}, FX, last)
    assert per["UK"] == pytest.approx(3 * 1000.0 * 0.01)  # ultimo prezzo noto
    assert per["IT"] == pytest.approx(4 * 5.0)  # costo medio (gia' EUR)


def test_failed_ticker_ignores_placeholder_price():
    per, _ = value_positions_eur(
        _pf(), UNI, {"US": 100, "UK": 2000, "IT": 100.0}, FX, {"IT": 6.0}, {"IT"}
    )
    assert per["IT"] == pytest.approx(4 * 6.0)  # non 4 * 100 (prezzo nominale)


def test_no_position_is_zero_and_never_negative():
    pf = _pf()
    pf["current_positions"] = {}
    per, total = value_positions_eur(pf, UNI, {}, FX)
    assert all(v == 0.0 for v in per.values())
    assert total == 100.0


def test_price_eur_zero_price_treated_as_missing():
    assert price_eur("A", "EUR", {"A": 0.0}, {"EUR": 1.0}, {"A": 7.0}, 3.0) == 7.0
