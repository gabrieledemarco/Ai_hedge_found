"""Valutazione del portafoglio in EUR, in un unico punto.

Prima la pipeline valutava le posizioni in due modi diversi: prima degli ordini i
titoli senza prezzo erano valutati al costo medio, DOPO gli ordini erano valutati
a 0. Il valore finale e' quello registrato nei log, quindi ogni sessione con
prezzi mancanti (es. i 5 titoli .MI) faceva crollare la equity curve di centinaia
di euro per poi risalire alla sessione successiva.

Ordine di preferenza per il prezzo di un titolo:
1. prezzo corrente (se disponibile e non di ripiego);
2. ultimo prezzo reale noto (da `price_history`);
3. costo medio di carico (gia' in EUR).
"""


def price_eur(
    ticker: str,
    currency: str,
    prices: dict,
    fx_rates: dict,
    last_known: dict,
    avg_price_eur: float,
    failed: set | frozenset = frozenset(),
) -> float:
    fx = fx_rates.get(currency, 1.0)
    current = prices.get(ticker)
    if ticker not in failed and current and current > 0:
        return current * fx
    last = last_known.get(ticker)
    if last and last > 0:
        return last * fx
    return avg_price_eur


def value_positions_eur(
    portfolio: dict,
    universe: dict,
    prices: dict,
    fx_rates: dict,
    last_known: dict | None = None,
    failed: set | frozenset = frozenset(),
) -> tuple[dict[str, float], float]:
    """Ritorna ({ticker: valore EUR della posizione}, totale incl. cassa)."""
    last_known = last_known or {}
    per_ticker: dict[str, float] = {}
    for ticker, info in universe.items():
        pos = portfolio["current_positions"].get(ticker, {})
        shares = pos.get("shares", 0)
        if shares <= 0:
            per_ticker[ticker] = 0.0
            continue
        per_ticker[ticker] = shares * price_eur(
            ticker,
            info["currency"],
            prices,
            fx_rates,
            last_known,
            pos.get("avg_price", 0.0),
            failed,
        )
    total = sum(per_ticker.values()) + portfolio["metadata"]["current_cash"]
    return per_ticker, total


def last_known_prices(portfolio: dict) -> dict:
    """Ultimo prezzo locale noto per ticker, dal log delle iterazioni di UN portafoglio
    (usato dalla dashboard per le posizioni senza prezzo nell'ultima rilevazione)."""
    last: dict[str, float] = {}
    for entry in portfolio.get("iterations_log", []):
        for ticker, price in entry.get("prices_used", {}).items():
            if price and price > 0:
                last[ticker] = price
    return last
