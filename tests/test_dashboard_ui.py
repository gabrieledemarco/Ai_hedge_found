"""Protegge la struttura della dashboard: sezioni, ordine, switch tema e dati incorporati.

La pagina e' un template statico (scripts/templates/dashboard.html) con i dati inseriti come
JSON: qui si verifica che il rendering produca una pagina completa e coerente."""
import json
import re

import dashboard_generator as dg

SECTIONS = ["overview", "performance", "metrics", "portfolio", "screener", "trades", "health"]
STRATEGIES = ["equal_weight", "momentum", "fundamental", "sentiment"]


def _portfolio(name):
    log = [
        {
            "timestamp": f"2026-07-0{d}T10:00:00+00:00",
            "total_value_eur": 3000.0 + d * 10,
            "current_cash": 100.0,
            "positions": {"AAPL": {"shares": 2, "avg_price": 150.0}},
            "prices_used": {"AAPL": 200.0},
            "transactions": (
                [{"action": "BUY", "ticker": "AAPL", "shares": 1, "price_eur": 100.0}]
                if d == 1
                else [{"action": "SELL", "ticker": "AAPL", "shares": 1, "price_eur": 110.0}]
                if d == 2
                else []
            ),
        }
        for d in range(1, 5)
    ]
    return {
        "strategy": name,
        "metadata": {"initial_capital": 3000.0, "current_cash": 100.0},
        "current_positions": {"AAPL": {"shares": 2, "avg_price": 150.0}},
        "iterations_log": log,
    }


def _html():
    return dg.build_html({n: _portfolio(n) for n in STRATEGIES}, {"sentiment": {}})


def _payload(html):
    raw = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(raw.group(1))


def test_sections_present_in_order():
    ids = re.findall(r'<section id="(\w+)"', _html())
    assert ids == SECTIONS


def test_nav_links_point_to_existing_sections():
    html = _html()
    nav = re.search(r'<nav class="nav".*?</nav>', html, re.S).group(0)
    assert re.findall(r'href="#(\w+)"', nav) == SECTIONS
    for section in SECTIONS:
        assert f'id="{section}"' in html


def test_theme_switch_is_light_by_default_and_applied_before_paint():
    html = _html()
    assert 'id="themeSwitch"' in html and 'role="switch"' in html
    # il tema scuro e' opt-in (localStorage / ?theme=dark), applicato prima del primo paint
    head = html.split("</head>")[0]
    assert "aihf.theme" in head and "data-theme" in head


def test_payload_embedded_for_all_strategies():
    payload = _payload(_html())
    assert list(payload["strategies"]) == STRATEGIES
    assert payload["strategies"]["momentum"]["metrics"]["n_days"] == 4
    assert payload["trades_summary"]["count"] == 4  # 1 round-trip per strategia


def test_no_strategy_data_renders_without_crashing():
    html = dg.build_html({}, {})
    assert '<section id="overview"' in html and _payload(html)["strategies"] == {}


def test_new_blocks_are_present_and_wired():
    html = _html()
    for element_id in ("marksChip", "relTable", "relSeg", "healthGrid", "marketNote", "metricsNote"):
        assert f'id="{element_id}"' in html
    payload = _payload(html)
    assert set(payload) >= {"market_note", "health", "benchmarks", "strategies"}
    assert {"signals", "fundamentals", "prices", "fx", "benchmarks", "dividends", "sessions"} <= set(payload["health"])
    strat = payload["strategies"]["equal_weight"]
    assert {"marks", "vs", "metrics_tr", "dividends_est_eur"} <= set(strat)
