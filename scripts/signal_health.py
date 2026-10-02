"""Copertura dei segnali: quanti ticker hanno un dato REALE per ciascun segnale.

Serve a non confondere "il segnale dice 0" con "il segnale non c'e'": una strategia
alimentata da dati vuoti non e' piu' data-driven, e va detto (log + Telegram).
"""

from strategies.signal_utils import has_fundamental, has_momentum, has_sentiment

MIN_COVERAGE = 0.5


def compute_coverage(signals: dict, universe: dict) -> dict[str, dict]:
    """{segnale: {"covered": n, "total": N, "ratio": 0-1}}"""
    tickers = list(universe)
    total = len(tickers)

    checks = {
        "momentum": lambda t: has_momentum(signals.get("momentum", {}).get(t)),
        "fundamentals": lambda t: has_fundamental(signals.get("fundamentals", {}).get(t)),
        "sentiment": lambda t: has_sentiment(signals.get("sentiment", {}).get(t)),
    }
    out = {}
    for name, fn in checks.items():
        covered = sum(1 for t in tickers if fn(t))
        out[name] = {
            "covered": covered,
            "total": total,
            "ratio": covered / total if total else 0.0,
        }
    return out


def format_health_warning(coverage: dict[str, dict]) -> str | None:
    """Testo di avviso per i segnali sotto soglia, None se tutto ok."""
    weak = [
        f"{name} {c['covered']}/{c['total']}"
        for name, c in coverage.items()
        if c["ratio"] < MIN_COVERAGE
    ]
    if not weak:
        return None
    return (
        "⚠️ Segnali con copertura bassa: "
        + ", ".join(weak)
        + ". Le strategie collegate usano liste di ripiego."
    )
