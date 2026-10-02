import json

import pytest

import fetch_fundamentals as ff
import fetch_sentiment as fs
import price_history as ph
from config import UNIVERSE
from metrics import collapse_to_daily, history_metrics
from signal_health import compute_coverage, format_health_warning


def _write_portfolio(tmp_path, name, entries):
    (tmp_path / f"{name}.json").write_text(json.dumps({"iterations_log": entries}))


def _entry(ts, prices):
    return {"timestamp": ts, "prices_used": prices, "total_value_eur": 3000.0}


# ── price_history ────────────────────────────────────────────────────────────

def test_history_skips_placeholder_days_and_keeps_last_per_day(tmp_path):
    entries = [
        _entry("2026-06-22T08:00:00+00:00", {"A": 100.0, "B": 150.0}),  # placeholder
        _entry("2026-06-24T08:00:00+00:00", {"A": 10.0, "B": 20.0}),
        _entry("2026-06-24T20:00:00+00:00", {"A": 11.0, "B": 21.0}),
        _entry("2026-06-25T08:00:00+00:00", {"A": 12.0, "B": 0.0}),  # B non valido
    ]
    _write_portfolio(tmp_path, "s", entries)
    h = ph.load_history(str(tmp_path))
    assert h["A"] == [("2026-06-24", 11.0), ("2026-06-25", 12.0)]
    assert h["B"] == [("2026-06-24", 21.0)]


def _linear_history(n, ticker="A", start=100.0, step=1.0):
    return {ticker: [(f"d{i:03d}", start + step * i) for i in range(n)]}


def test_price_signals_values():
    sig = ph.compute_price_signals(_linear_history(80))
    m = sig["momentum"]["A"]
    assert m["return_3m"] == pytest.approx((179.0 / (179.0 - 63) - 1), abs=1e-3)
    assert m["return_1m"] == pytest.approx(179.0 / (179.0 - 21) - 1, abs=1e-3)
    assert sig["volatility"]["A"]["vol_60d"] > 0
    assert sig["trend"] == {}  # < 200 giorni: nessun filtro di trend


def test_price_signals_omit_instead_of_zero_when_history_short():
    sig = ph.compute_price_signals({**_linear_history(5), **_linear_history(40, "B")})
    assert "A" not in sig["momentum"] and "A" not in sig["volatility"]
    assert "B" not in sig["momentum"]  # 40 < 64 osservazioni
    assert "B" in sig["volatility"]


def test_trend_signal_with_enough_history():
    up = ph.compute_price_signals(_linear_history(220))
    down = ph.compute_price_signals(_linear_history(220, step=-0.2))
    assert up["trend"]["A"]["above_ma200"] is True
    assert down["trend"]["A"]["above_ma200"] is False


def test_real_repo_history_is_loadable():
    # smoke test sui dati committati nel repo
    h = ph.load_history()
    assert h
    assert all(p > 0 for series in h.values() for _, p in series)


# ── fetch_fundamentals ───────────────────────────────────────────────────────

def test_score_fundamental_none_without_metrics():
    assert ff.score_fundamental({}) is None
    assert ff.score_fundamental({"trailingPE": 10, "returnOnEquity": 0.3}) > 0.5


def test_fetch_momentum_uses_fallback_and_omits_unknown(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            pass

        def history(self, **k):
            raise RuntimeError("blocked")

    monkeypatch.setattr(ff.yf, "Ticker", Boom)
    fallback = {"A": {"return_3m": 0.1, "return_1m": 0.02, "source": "price_history"}}
    out = ff.fetch_momentum({"A": {}, "B": {}}, fallback=fallback)
    assert out == fallback  # B omesso, mai 0.0


# ── FinBERT ──────────────────────────────────────────────────────────────────

def test_finbert_scores_headlines_with_loaded_model(monkeypatch):
    monkeypatch.setattr(
        fs, "_get_finbert", lambda: (lambda h: [{"label": "positive", "score": 0.5}])
    )
    assert fs.run_finbert_on_headlines(["a", "b"]) == pytest.approx(0.5)


def test_finbert_model_is_cached_across_calls(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(fs, "_FINBERT", sentinel)
    assert fs._get_finbert() is sentinel  # nessun nuovo caricamento


# ── coverage ─────────────────────────────────────────────────────────────────

def test_coverage_flags_legacy_placeholders():
    signals = {
        "momentum": {t: {"return_3m": 0.0, "return_1m": 0.0} for t in UNIVERSE},
        "fundamentals": {t: {"f_score": 0.5} for t in UNIVERSE},
        "sentiment": {
            t: {"score": 0.1, "num_articles": 5 if i < 10 else 0}
            for i, t in enumerate(UNIVERSE)
        },
    }
    cov = compute_coverage(signals, UNIVERSE)
    assert cov["momentum"]["covered"] == 0
    assert cov["fundamentals"]["covered"] == 0
    assert cov["sentiment"]["covered"] == 10
    warning = format_health_warning(cov)
    assert "momentum 0/20" in warning and "fundamentals 0/20" in warning
    assert "sentiment" not in warning  # 50% non e' sotto soglia


def test_no_warning_when_signals_healthy():
    signals = {
        "momentum": {t: {"return_3m": 0.1, "return_1m": 0.02} for t in UNIVERSE},
        "fundamentals": {t: {"f_score": 0.7, "pe_ratio": 12.0} for t in UNIVERSE},
        "sentiment": {t: {"score": 0.1, "num_articles": 5} for t in UNIVERSE},
    }
    assert format_health_warning(compute_coverage(signals, UNIVERSE)) is None


# ── metriche dashboard ───────────────────────────────────────────────────────

def _log(values_by_day, per_day=3):
    out = []
    for d, v in enumerate(values_by_day):
        for k in range(per_day):
            out.append(
                {"timestamp": f"2026-07-{d + 1:02d}T{8 + k:02d}:00:00+00:00",
                 "total_value_eur": v}
            )
    return out


def test_collapse_to_daily_takes_last_value_of_each_day():
    log = _log([100.0, 110.0])  # 3 voci per giorno
    log[0]["total_value_eur"] = 99.0  # voce del mattino: deve essere ignorata
    assert collapse_to_daily(log) == [100.0, 110.0]


def test_history_metrics_not_inflated_by_intraday_entries():
    values = [3000.0, 3030.0, 3000.0, 3060.0, 3090.0]
    m1 = history_metrics(_log(values, per_day=1))
    m3 = history_metrics(_log(values, per_day=3))
    # stessa performance giornaliera, 3 iterazioni al giorno: stessi indicatori
    assert m3["sharpe"] == pytest.approx(m1["sharpe"])
    assert m3["ann_return"] == pytest.approx(m1["ann_return"])
    assert m3["max_drawdown"] == pytest.approx(m1["max_drawdown"])
    assert m3["n_days"] == len(values)
    assert m3["n_entries"] == 3 * len(values)
    assert m3["total_return"] == pytest.approx(3.0)  # +3% in punti percentuali


def test_history_metrics_empty():
    assert history_metrics([]) == {}


# ── sentiment: risparmio quota Alpha Vantage ─────────────────────────────────

from datetime import datetime, timedelta, timezone  # noqa: E402


def _fake_av(calls):
    def fetch(ticker):
        calls.append(ticker)
        return {"score": 0.0, "label": "neutral", "num_articles": 0, "headlines": []}

    return fetch


def test_sentiment_skips_recently_empty_tickers(monkeypatch):
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    prev = {
        "EU": {"score": 0.0, "num_articles": 0, "checked_at": (now - timedelta(days=2)).isoformat()},
        "OLD": {"score": 0.0, "num_articles": 0, "checked_at": (now - timedelta(days=9)).isoformat()},
        "LEGACY": {"score": 0.0, "num_articles": 0},  # senza data: ricontrollare
        "US": {"score": 0.2, "num_articles": 7, "checked_at": now.isoformat()},
    }
    calls = []
    monkeypatch.setattr(fs, "fetch_av_news_sentiment", _fake_av(calls))
    monkeypatch.setattr(fs.time, "sleep", lambda s: None)
    out = fs.fetch_all_sentiment(
        {t: {} for t in prev}, previous=prev, now=now
    )
    assert sorted(calls) == ["LEGACY", "OLD", "US"]  # solo EU saltato
    assert out["EU"] == prev["EU"]
    assert out["OLD"]["checked_at"] == now.isoformat()  # timbrato di nuovo


def test_sentiment_without_previous_fetches_everything(monkeypatch):
    calls = []
    monkeypatch.setattr(fs, "fetch_av_news_sentiment", _fake_av(calls))
    sleeps = []
    monkeypatch.setattr(fs.time, "sleep", lambda s: sleeps.append(s))
    fs.fetch_all_sentiment({"A": {}, "B": {}, "C": {}})
    assert calls == ["A", "B", "C"]
    assert sleeps == [13, 13]  # nessuna attesa dopo l'ultima ne' prima della prima
