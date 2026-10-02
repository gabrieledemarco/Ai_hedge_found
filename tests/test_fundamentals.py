"""Fonti dei fondamentali, cache e rotazione della quota (fundamentals_sources + fetch_fundamentals)."""
from datetime import datetime, timedelta, timezone

import pytest

import fetch_fundamentals as ff
import fundamentals_sources as fs

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
UNIVERSE = {"AAA": {}, "BBB.MI": {}, "CCC.L": {}}

AV_IBM = {  # forma reale della risposta OVERVIEW (valori come stringhe)
    "Symbol": "IBM", "PERatio": "19.53", "TrailingPE": "19.53", "ReturnOnEquityTTM": "0.345",
    "MarketCapitalization": "212564361000", "PriceToBookRatio": "6.33",
    "QuarterlyRevenueGrowthYOY": "0.011",
}


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _real(days_old, f_score=0.7):
    return {
        "f_score": f_score, "pe_ratio": 15.0, "roe": 0.2,
        "fetched_at": (NOW - timedelta(days=days_old)).isoformat(),
    }


# ── Alpha Vantage OVERVIEW ───────────────────────────────────────────────────

def test_av_symbol_mapping():
    assert fs.av_symbol("ENI.MI") == "ENI.MIL"
    assert fs.av_symbol("ULVR.L") == "ULVR.LON"
    assert fs.av_symbol("AAPL") == "AAPL"


def test_overview_maps_to_yfinance_keys(monkeypatch):
    monkeypatch.setattr(fs.requests, "get", lambda *a, **k: _Resp(AV_IBM))
    info = fs.fetch_alpha_vantage_overview("IBM", "k")
    assert info["trailingPE"] == pytest.approx(19.53)
    assert info["returnOnEquity"] == pytest.approx(0.345)
    assert info["marketCap"] == 212564361000.0
    assert "freeCashflow" not in info and "debtToEquity" not in info  # AV non li fornisce
    score, n = ff._score_and_count(info)
    assert n == 2 and 0.0 <= score <= 1.0  # P/E + ROE


def test_overview_none_strings_and_missing_core_metrics(monkeypatch):
    data = {"Symbol": "X", "PERatio": "None", "ReturnOnEquityTTM": "None", "MarketCapitalization": "5"}
    monkeypatch.setattr(fs.requests, "get", lambda *a, **k: _Resp(data))
    assert fs.fetch_alpha_vantage_overview("X", "k") is None  # senza P/E ne' ROE: nessun dato


def test_overview_empty_and_unknown_symbol(monkeypatch):
    monkeypatch.setattr(fs.requests, "get", lambda *a, **k: _Resp({}))
    assert fs.fetch_alpha_vantage_overview("ZZZ", "k") is None


def test_overview_quota_message_raises(monkeypatch):
    msg = {"Information": "Thank you for using Alpha Vantage! standard rate limit is 25 requests per day."}
    monkeypatch.setattr(fs.requests, "get", lambda *a, **k: _Resp(msg))
    with pytest.raises(fs.QuotaExceeded):
        fs.fetch_alpha_vantage_overview("IBM", "k")


# ── Rotazione / freschezza ───────────────────────────────────────────────────

def test_needs_refresh_rules():
    assert fs.needs_refresh(None, NOW)
    assert fs.needs_refresh({"error": "no_data"}, NOW)
    assert fs.needs_refresh({"f_score": 0.5}, NOW)  # placeholder storico
    assert fs.needs_refresh({"f_score": 0.7, "pe_ratio": 12.0}, NOW)  # reale ma senza data
    assert not fs.needs_refresh(_real(3), NOW)
    assert fs.needs_refresh(_real(30), NOW, max_age_days=14)


def test_plan_refresh_orders_missing_first_then_oldest():
    previous = {"AAA": _real(40), "BBB.MI": _real(20), "CCC.L": {"error": "x"}}
    # prima chi non ha un dato reale, poi dal piu' vecchio (AAA 40 giorni, BBB.MI 20)
    assert fs.plan_refresh(UNIVERSE, previous, NOW, 14) == ["CCC.L", "AAA", "BBB.MI"]
    # i freschi non compaiono, a meno di --force
    previous["AAA"] = _real(1)
    assert "AAA" not in fs.plan_refresh(UNIVERSE, previous, NOW, 14)
    assert "AAA" in fs.plan_refresh(UNIVERSE, previous, NOW, 14, force=True)


# ── fetch_all_fundamentals ───────────────────────────────────────────────────

class _Ticker:
    infos: dict = {}

    def __init__(self, symbol):
        self.symbol = symbol

    @property
    def info(self):
        info = self.infos.get(self.symbol)
        if isinstance(info, Exception):
            raise info
        return info or {}


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(ff.time, "sleep", lambda s: None)
    monkeypatch.setattr(ff, "yf", type("YF", (), {"Ticker": _Ticker}))


def test_fresh_entries_are_reused_without_any_call(no_sleep, monkeypatch):
    _Ticker.infos = {}
    monkeypatch.setattr(fs, "fetch_alpha_vantage_overview",
                        lambda *a: pytest.fail("nessuna chiamata attesa"))
    previous = {t: _real(2) for t in UNIVERSE}
    out = ff.fetch_all_fundamentals(UNIVERSE, previous=previous, av_key="k", now=NOW)
    assert out == previous


def test_yahoo_success_records_source_and_timestamp(no_sleep):
    _Ticker.infos = {"AAA": {"trailingPE": 15, "returnOnEquity": 0.3, "freeCashflow": 10, "marketCap": 100, "debtToEquity": 50}}
    out = ff.fetch_all_fundamentals({"AAA": {}}, now=NOW)
    e = out["AAA"]
    assert e["source"] == "yfinance" and e["metrics_used"] == 4
    assert e["fetched_at"] == NOW.isoformat()


def test_falls_back_to_alpha_vantage_within_budget(no_sleep, monkeypatch):
    _Ticker.infos = {}  # Yahoo non risponde (come su GitHub Actions)
    calls = []

    def fake_av(ticker, key):
        calls.append(ticker)
        return {"trailingPE": 18.0, "returnOnEquity": 0.25}

    monkeypatch.setattr(fs, "fetch_alpha_vantage_overview", fake_av)
    out = ff.fetch_all_fundamentals(UNIVERSE, av_key="k", av_budget=2, now=NOW, sleep=lambda s: None)
    assert len(calls) == 2  # budget rispettato
    sources = sorted(e.get("source", "error") for e in out.values())
    assert sources == ["alpha_vantage", "alpha_vantage", "error"]


def test_no_key_means_no_alpha_vantage(no_sleep, monkeypatch):
    _Ticker.infos = {}
    monkeypatch.setattr(fs, "fetch_alpha_vantage_overview",
                        lambda *a: pytest.fail("senza chiave non si chiama Alpha Vantage"))
    out = ff.fetch_all_fundamentals(UNIVERSE, av_key="", now=NOW)
    assert all("error" in e for e in out.values())


def test_quota_exhaustion_stops_further_calls(no_sleep, monkeypatch):
    _Ticker.infos = {}
    calls = []

    def quota(ticker, key):
        calls.append(ticker)
        raise fs.QuotaExceeded("limit")

    monkeypatch.setattr(fs, "fetch_alpha_vantage_overview", quota)
    out = ff.fetch_all_fundamentals(UNIVERSE, av_key="k", av_budget=5, now=NOW, sleep=lambda s: None)
    assert len(calls) == 1  # dopo il primo messaggio di quota non si insiste
    assert all("error" in e for e in out.values())


def test_failed_refresh_keeps_previous_real_value_via_merge(no_sleep):
    from signals_utils import merge_fundamentals

    _Ticker.infos = {"AAA": RuntimeError("blocked")}
    previous = {"AAA": _real(40, f_score=0.8)}
    fetched = ff.fetch_all_fundamentals({"AAA": {}}, previous=previous, now=NOW)
    assert "error" in fetched["AAA"]
    assert merge_fundamentals(fetched, previous)["AAA"] == previous["AAA"]
