"""Nota di mercato giornaliera per il report Telegram.

Per default e' generata da template deterministici: nessuna AI, nessuna API key,
nessun costo. Opzionalmente si puo' farla riscrivere da un LLM tramite un
endpoint compatibile OpenAI (OpenAI, Ollama locale, vLLM, ...), configurato solo
con variabili d'ambiente:

    LLM_BASE_URL   es. http://localhost:11434/v1
    LLM_MODEL      es. llama3.1
    LLM_API_KEY    opzionale (non serve per endpoint locali)

Se LLM_BASE_URL o LLM_MODEL mancano, o la chiamata fallisce, si usa il template.
"""
import os

import requests

LABELS = {
    "equal_weight": "Equal Weight",
    "momentum": "Momentum",
    "fundamental": "Fundamental",
    "sentiment": "Sentiment",
}


def _return_pct(result: dict, default_initial: float) -> float:
    initial = result["portfolio"]["metadata"].get("initial_capital", default_initial)
    if not initial:
        return 0.0
    return (result["total_value_eur"] - initial) / initial * 100


def build_template_note(
    strategy_results: dict, signals: dict, initial_capital: float = 3000.0
) -> str:
    """Riassunto testuale deterministico. Funzione pura: stessi input, stesso testo."""
    valid = {k: v for k, v in strategy_results.items() if v}
    if not valid:
        return "Nessun dato di strategia disponibile."

    rets = {k: _return_pct(v, initial_capital) for k, v in valid.items()}
    best = max(rets, key=rets.get)
    worst = min(rets, key=rets.get)
    lines = [
        "Migliore: {} ({:+.1f}%). Peggiore: {} ({:+.1f}%).".format(
            LABELS.get(best, best), rets[best], LABELS.get(worst, worst), rets[worst]
        )
    ]

    n_trades = sum(len(v["transactions"]) for v in valid.values())
    lines.append(
        f"Oggi {n_trades} operazioni eseguite."
        if n_trades
        else "Oggi nessuna operazione: i pesi restano entro la soglia di ribilanciamento."
    )

    sentiment = signals.get("sentiment", {})
    bullish = sorted(
        (t for t, d in sentiment.items() if d.get("num_articles", 0) > 0),
        key=lambda t: sentiment[t].get("score", 0.0),
        reverse=True,
    )[:3]
    if bullish:
        lines.append(
            "Sentiment più positivo: "
            + ", ".join(f"{t} ({sentiment[t]['score']:+.2f})" for t in bullish)
            + "."
        )

    momentum = signals.get("momentum", {})
    leaders = sorted(
        momentum, key=lambda t: momentum[t].get("return_3m", 0.0), reverse=True
    )[:3]
    if leaders:
        lines.append(
            "Momentum a 3 mesi più forte: "
            + ", ".join(f"{t} ({momentum[t]['return_3m']:+.1%})" for t in leaders)
            + "."
        )

    heavy_cash = [
        LABELS.get(k, k)
        for k, v in valid.items()
        if v["total_value_eur"] > 0
        and v["portfolio"]["metadata"].get("current_cash", 0) / v["total_value_eur"]
        > 0.2
    ]
    if heavy_cash:
        lines.append("Cassa oltre il 20% in: " + ", ".join(heavy_cash) + ".")
    return "\n".join(lines)


def _llm_enabled() -> bool:
    return bool(os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_MODEL"))


def _rewrite_with_llm(template_note: str) -> str | None:
    base = os.environ["LLM_BASE_URL"].rstrip("/")
    headers = {"Content-Type": "application/json"}
    if os.environ.get("LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['LLM_API_KEY']}"
    payload = {
        "model": os.environ["LLM_MODEL"],
        "temperature": 0.3,
        "max_tokens": 250,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Sei un analista di un fondo di paper trading. Riscrivi in "
                    "italiano, in massimo 5 righe, la nota seguente. Usa solo i "
                    "fatti presenti: non aggiungere numeri, titoli o consigli."
                ),
            },
            {"role": "user", "content": template_note},
        ],
    }
    try:
        resp = requests.post(
            f"{base}/chat/completions", json=payload, headers=headers, timeout=30
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        return text or None
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        print(f"[WARN] LLM note failed, using template: {e}")
        return None


def generate_market_note(
    strategy_results: dict, signals: dict, initial_capital: float = 3000.0
) -> str:
    note = build_template_note(strategy_results, signals, initial_capital)
    if _llm_enabled():
        return _rewrite_with_llm(note) or note
    return note
