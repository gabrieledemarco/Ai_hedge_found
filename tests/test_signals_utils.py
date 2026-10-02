import pytest

from signals_utils import enrich_signals, merge_fundamentals

UNIVERSE = {"AAA": {}, "BBB": {}}


def _history(n=80):
    """Storico giornaliero sintetico: AAA sale di 1 EUR al giorno, BBB ha pochi punti."""
    days = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    return {
        "AAA": [(d, 100.0 + i) for i, d in enumerate(days)],
        "BBB": [(days[0], 10.0), (days[1], 11.0)],
    }


def test_enrich_replaces_placeholder_momentum_with_real_values():
    signals = {
        "momentum": {
            "AAA": {"return_3m": 0.0, "return_1m": 0.0},
            "BBB": {"return_3m": 0.5, "return_1m": 0.1},
        },
        "fundamentals": {"AAA": {"f_score": 0.5}},
        "sentiment": {"AAA": {"num_articles": 3}},
    }
    out = enrich_signals(signals, UNIVERSE, _history())
    assert out["momentum"]["AAA"]["return_3m"] > 0  # calcolato dallo storico
    assert out["momentum"]["BBB"]["return_3m"] == 0.5  # valore reale gia' presente: intatto
    assert out["status"]["momentum_from_history"] == 1
    assert out["status"]["fundamentals_real"] is False  # 0.5 senza metriche = placeholder
    assert out["status"]["sentiment_real"] is True
    assert signals["momentum"]["AAA"]["return_3m"] == 0.0  # input non mutato


def test_enrich_without_enough_history_leaves_momentum_missing():
    out = enrich_signals({"momentum": {}}, UNIVERSE, {"AAA": [("2026-01-01", 1.0)]})
    assert "AAA" not in out["momentum"]
    assert out["status"]["momentum_real"] is False


def test_merge_fundamentals_does_not_clobber_real_data():
    old = {"AAA": {"f_score": 0.8, "pe_ratio": 15, "roe": 0.2}, "BBB": {"f_score": 0.5}}
    new = {"AAA": {"error": "no_data"}, "BBB": {"f_score": 0.6, "roe": 0.1}}
    merged = merge_fundamentals(new, old)
    assert merged["AAA"] == old["AAA"]  # fetch fallito: resta il dato reale precedente
    assert merged["BBB"] == new["BBB"]


def test_merge_fundamentals_accepts_new_real_data():
    old = {"AAA": {"f_score": 0.8, "pe_ratio": 15}}
    new = {"AAA": {"f_score": 0.4, "pe_ratio": 30}}
    assert merge_fundamentals(new, old)["AAA"]["f_score"] == pytest.approx(0.4)


def test_combined_history_prefers_the_longest_series_per_ticker(tmp_path):
    import json

    import price_history as ph

    pdir = tmp_path / "portfolios"
    pdir.mkdir()
    log = [
        {"timestamp": f"2026-01-{d:02d}T10:00:00+00:00", "prices_used": {"AAA": 100.0 + d}}
        for d in range(1, 6)
    ]
    (pdir / "s.json").write_text(json.dumps({"iterations_log": log}))
    stored = {
        "AAA": {f"2026-01-{d:02d}": 1.0 for d in range(1, 4)},  # piu' corta dei log
        "BBB.MI": {f"2026-01-{d:02d}": 5.0 for d in range(1, 11)},  # solo nel file persistito
        "FX:USD": {"2026-01-01": 0.9},
    }
    path = tmp_path / "ph.json"
    path.write_text(json.dumps(stored))

    out = ph.combined_history(str(pdir), str(path))
    assert len(out["AAA"]) == 5 and out["AAA"][0][1] == 101.0  # restano i log
    assert len(out["BBB.MI"]) == 10  # il titolo con log incompleti usa il file persistito
    assert "FX:USD" not in out  # i cambi non sono prezzi di titoli
