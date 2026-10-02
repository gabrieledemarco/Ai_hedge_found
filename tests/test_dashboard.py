import json

import pytest
import re

from dashboard_data import build_payload, extract_completed_trades
from dashboard_generator import _render


def _portfolio():
    def entry(day, total, txns=None):
        return {
            "timestamp": f"2026-03-{day:02d}T12:00:00+00:00",
            "session": "sera",
            "total_value_eur": total,
            "current_cash": total,
            "positions": {},
            "prices_used": {},
            "transactions": txns or [],
        }

    log = [
        entry(2, 3000.0, [{"action": "BUY", "ticker": "AAPL", "shares": 2, "price_eur": 100.0}]),
        entry(3, 3010.0),
        entry(4, 3020.0, [{"action": "SELL", "ticker": "AAPL", "shares": 1, "price_eur": 110.0}]),
    ]
    return {
        "metadata": {"initial_capital": 3000.0, "current_cash": 3020.0},
        "current_positions": {"AAPL": {"shares": 1, "avg_price": 100.0}},
        "iterations_log": log,
    }


def test_completed_trades_fifo():
    trades = extract_completed_trades({"equal_weight": _portfolio()})
    assert len(trades) == 1
    assert trades[0]["pnl_eur"] == 10.0 and trades[0]["shares"] == 1


def test_payload_and_render_roundtrip():
    payload = build_payload({"equal_weight": _portfolio()}, {}, {})
    s = payload["strategies"]["equal_weight"]
    assert s["metrics"]["n_days"] == 3
    assert s["positions"][0]["ticker"] == "AAPL"

    html = _render(payload)
    assert "__DATA__" not in html
    match = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S)
    assert json.loads(match.group(1))["generated_at"] == payload["generated_at"]


def test_render_escapes_script_terminator():
    payload = build_payload({}, {}, {})
    payload["note"] = "</script><b>x</b>"
    assert "</script><b>" not in _render(payload)


def test_live_prices_override_positions_and_value():
    portfolio = _portfolio()
    portfolio["iterations_log"][-1]["prices_used"] = {"AAPL": 100.0}
    base = build_payload({"equal_weight": portfolio}, {}, {})["strategies"]["equal_weight"]
    assert base["live_value"] is None

    live = build_payload({"equal_weight": portfolio}, {}, {}, {"AAPL": 150.0})["strategies"]["equal_weight"]
    pos = live["positions"][0]
    assert pos["live"] is True and pos["stale"] is False
    # AAPL e' quotata in USD: il valore dipende dal cambio, ma il prezzo live deve prevalere
    assert pos["price_eur"] > base["positions"][0]["price_eur"]
    assert live["live_value"] > base["metrics"]["final"] - 1e-9


# ── Benchmark in EUR, allineamento, operazioni, stato dei dati ───────────────

def test_foreign_benchmark_is_converted_to_eur_with_historical_fx():
    from dashboard_data import _benchmarks

    ph = {
        "SPY": {"2026-03-02": 100.0, "2026-03-03": 110.0},
        "SWDA.MI": {"2026-03-02": 50.0, "2026-03-03": 51.0},
        "FX:USD": {"2026-03-02": 0.5, "2026-03-03": 0.6},
    }
    out = _benchmarks(ph, "2026-03-01")
    assert out["SPY"]["series"] == [["2026-03-02", 50.0], ["2026-03-03", 66.0]]  # 100*0.5, 110*0.6
    assert out["SPY"]["currency"] == "USD" and out["SPY"]["basis"] == "total_return"
    assert out["SWDA.MI"]["series"][-1] == ["2026-03-03", 51.0]  # gia' in EUR: invariato


def test_to_price_dates_uses_the_previous_trading_day():
    from dashboard_data import _to_price_dates

    trading = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"]  # lun-ven
    daily = [("2026-03-02", 1.0), ("2026-03-03", 2.0), ("2026-03-07", 3.0)]  # lun, mar, sab
    # lun: nessuna data di borsa precedente (scartato); mar -> lun; sab -> ven
    assert _to_price_dates(daily, trading) == [("2026-03-02", 2.0), ("2026-03-06", 3.0)]


def test_marks_group_transactions_by_day():
    from dashboard_data import _marks

    log = [
        {"timestamp": "2026-03-02T07:00:00+00:00", "transactions": [{"action": "BUY", "ticker": "AAPL", "shares": 2}]},
        {"timestamp": "2026-03-02T15:00:00+00:00", "transactions": [{"action": "SELL", "ticker": "KO", "shares": 1}]},
        {"timestamp": "2026-03-03T07:00:00+00:00", "transactions": []},
    ]
    assert _marks(log) == [{"d": "2026-03-02", "b": ["AAPL ×2"], "s": ["KO ×1"]}]


def _long_portfolio(days=30):
    from datetime import date, timedelta

    start, log = date(2026, 3, 2), []
    for i in range(days):
        d = start + timedelta(days=i)
        px = 100.0 + (i % 5) * 2 + i * 0.3
        log.append({
            "timestamp": f"{d.isoformat()}T12:00:00+00:00", "session": "sera",
            "total_value_eur": 1000.0 + px, "current_cash": 1000.0 - 5 * px * 0 + 0.0,
            "positions": {"AAPL": {"shares": 5, "avg_price": 100.0}},
            "prices_used": {"AAPL": px}, "fx_rates": {"USD": 1.0},
            "transactions": [{"action": "BUY", "ticker": "AAPL", "shares": 5, "price_eur": px}] if i == 0 else [],
        })
    return {"metadata": {"initial_capital": 1000.0, "current_cash": 1000.0},
            "current_positions": {"AAPL": {"shares": 5, "avg_price": 100.0}}, "iterations_log": log}


def test_payload_includes_relative_metrics_dividends_marks_note_and_health():
    from datetime import date, timedelta

    pf = _long_portfolio()
    start = date(2026, 3, 1)
    days = [(start + timedelta(days=i)).isoformat() for i in range(40)]
    ph = {
        "SWDA.MI": {d: 100.0 + i * 0.4 + (i % 3) for i, d in enumerate(days)},
        "DIV:AAPL": {"2026-03-10": 2.0},
    }
    payload = build_payload({"equal_weight": pf}, {"momentum": {}, "sentiment": {}}, ph)
    s = payload["strategies"]["equal_weight"]
    # 5 azioni x 2.0 USD, convertiti col cambio di ripiego 0.92 (nessun FX storico fornito)
    assert s["dividends_est_eur"] == pytest.approx(5 * 2.0 * 0.92)
    assert s["metrics_tr"]["total_return"] > s["metrics"]["total_return"]
    assert s["marks"] == [{"d": "2026-03-02", "b": ["AAPL ×5"], "s": []}]
    vs = s["vs"]["SWDA.MI"]
    assert vs["n_obs"] >= 20 and vs["beta"] is not None and vs["tracking_error"] > 0
    assert "Migliore" in payload["market_note"]["text"]
    health = payload["health"]
    assert set(health["signals"]) == {"momentum", "fundamentals", "sentiment"}
    assert health["sessions"]["total"] == 30 and health["dividends"]["last_ex_date"] == "2026-03-10"
    assert "AAPL" not in health["prices"]["missing_tickers"]


def test_short_history_gives_no_relative_metrics():
    ph = {"SWDA.MI": {"2026-03-02": 100.0, "2026-03-03": 101.0, "2026-03-04": 102.0}}
    payload = build_payload({"equal_weight": _portfolio()}, {}, ph)
    assert payload["strategies"]["equal_weight"]["vs"]["SWDA.MI"] is None
