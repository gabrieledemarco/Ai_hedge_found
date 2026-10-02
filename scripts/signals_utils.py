"""
Utilita' sui segnali (data/signals.json) per pipeline e dashboard.

Cosa conta come dato REALE e' definito in `strategies/signal_utils.py` (has_momentum,
has_fundamental, has_sentiment); qui ci sono solo:
  * `enrich_signals`: sostituisce i momentum finti (0.0/0.0) con quelli calcolati dallo
    storico prezzi locale e aggiunge `status` (segnali reali o no) per la dashboard;
  * `merge_fundamentals`: un fetch fallito non cancella dati fondamentali reali precedenti.
"""

from price_history import combined_history, compute_price_signals
from strategies.signal_utils import has_fundamental, has_momentum, has_sentiment


def enrich_signals(signals: dict, universe: dict, history: dict | None = None) -> dict:
    """Copia dei segnali con il momentum reale al posto dei placeholder, piu' `status`.

    `history` e' lo storico prezzi (price_history.combined_history);
    se omesso viene caricato da price_history.combined_history(). L'input non viene modificato.
    """
    history = combined_history() if history is None else history
    enriched = dict(signals)
    momentum = dict(signals.get("momentum", {}))
    computed = compute_price_signals(
        {t: s for t, s in history.items() if t in universe}
    )["momentum"]
    filled = 0
    for ticker, values in computed.items():
        if not has_momentum(momentum.get(ticker)):
            momentum[ticker] = values
            filled += 1
    enriched["momentum"] = momentum

    tickers = list(universe)
    enriched["status"] = {
        "fundamentals_real": any(
            has_fundamental(signals.get("fundamentals", {}).get(t)) for t in tickers
        ),
        "sentiment_real": any(
            has_sentiment(signals.get("sentiment", {}).get(t)) for t in tickers
        ),
        "momentum_real": any(has_momentum(momentum.get(t)) for t in tickers),
        "momentum_from_history": filled,
    }
    return enriched


def merge_fundamentals(new: dict, old: dict) -> dict:
    """Non sovrascrive dati reali precedenti con voci senza dati (fetch fallito)."""
    merged = {}
    for ticker, entry in new.items():
        previous = old.get(ticker)
        if not has_fundamental(entry) and has_fundamental(previous):
            merged[ticker] = previous
        else:
            merged[ticker] = entry
    return merged
