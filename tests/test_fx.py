import json

import pytest

import fx
from config import FX_FALLBACK


def _fetcher(rate, calls):
    def fetch(base, quote, key):
        calls.append((base, quote))
        return rate

    return fetch


def test_fetches_once_per_day_then_uses_cache(tmp_path):
    path = str(tmp_path / "fx.json")
    calls = []
    f = _fetcher(0.86, calls)
    assert fx.get_fx_rate("USD", api_key="k", path=path, today="2026-10-02", fetch=f) == 0.86
    assert fx.get_fx_rate("USD", api_key="k", path=path, today="2026-10-02", fetch=f) == 0.86
    assert len(calls) == 1  # seconda richiesta: dalla cache, nessuna chiamata API
    assert json.load(open(path))["USD"] == {"rate": 0.86, "date": "2026-10-02"}


def test_failure_uses_last_known_rate_not_hardcoded_fallback(tmp_path):
    path = str(tmp_path / "fx.json")
    fx.save_cache({"USD": {"rate": 0.85, "date": "2026-10-01"}}, path)
    rate = fx.get_fx_rate(
        "USD", api_key="k", path=path, today="2026-10-02", fetch=_fetcher(None, [])
    )
    assert rate == 0.85
    assert rate != FX_FALLBACK["USD"]


def test_no_cache_and_no_source_uses_config_fallback(tmp_path):
    path = str(tmp_path / "missing.json")
    rate = fx.get_fx_rate(
        "USD", api_key="", path=path, today="2026-10-02", fetch=_fetcher(None, [])
    )
    assert rate == FX_FALLBACK["USD"]


def test_frankfurter_is_tried_before_alpha_vantage(monkeypatch):
    calls = []
    monkeypatch.setattr(fx, "fetch_frankfurter_rate", lambda b, q: calls.append("ecb") or 0.89)
    monkeypatch.setattr(
        fx, "fetch_alpha_vantage_rate", lambda b, q, k: calls.append("av") or 0.5
    )
    assert fx.fetch_rate("USD", "EUR", "key") == 0.89
    assert calls == ["ecb"]  # Alpha Vantage (quota limitata) non viene nemmeno chiamata


def test_alpha_vantage_used_only_when_frankfurter_fails_and_key_present(monkeypatch):
    monkeypatch.setattr(fx, "fetch_frankfurter_rate", lambda b, q: None)
    monkeypatch.setattr(fx, "fetch_alpha_vantage_rate", lambda b, q, k: 0.88)
    assert fx.fetch_rate("USD", "EUR", "key") == 0.88
    assert fx.fetch_rate("USD", "EUR", "") is None


def test_implausible_rate_is_rejected(tmp_path):
    path = str(tmp_path / "fx.json")
    fx.save_cache({"USD": {"rate": 0.85, "date": "2026-10-01"}}, path)
    rate = fx.get_fx_rate(
        "USD", api_key="k", path=path, today="2026-10-02", fetch=_fetcher(8.5, [])
    )
    assert rate == 0.85  # 8.5 scartato (10x), resta l'ultimo noto


def test_same_currency_and_pence(tmp_path):
    path = str(tmp_path / "fx.json")
    assert fx.get_fx_rate("EUR", "EUR", path=path) == 1.0
    calls = []
    rate = fx.get_fx_rate(
        "GBp", api_key="k", path=path, today="2026-10-02", fetch=_fetcher(1.15, calls)
    )
    assert rate == pytest.approx(0.0115)
    assert calls == [("GBP", "EUR")]


def test_corrupt_cache_is_ignored(tmp_path):
    path = tmp_path / "fx.json"
    path.write_text("{not json")
    assert fx.load_cache(str(path)) == {}


def test_iteration_log_records_fx_rates(tmp_path, monkeypatch):
    import portfolio_io

    monkeypatch.setattr(portfolio_io, "PORTFOLIOS_DIR", str(tmp_path))
    pf = {
        "metadata": {"current_cash": 10.0},
        "current_positions": {},
        "iterations_log": [],
    }
    portfolio_io.log_iteration_for_strategy(
        "s", pf, "sera", 10.0, [], {}, "", fx_rates={"USD": 0.8512345678}
    )
    assert pf["iterations_log"][-1]["fx_rates"] == {"USD": 0.851235}
