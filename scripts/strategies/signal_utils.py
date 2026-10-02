"""Cosa conta come dato REALE in signals.json.

Le versioni precedenti della pipeline scrivevano valori nominali quando il fetch
falliva (momentum 0.0/0.0, f_score 0.5 senza metriche). Qui li riconosciamo, cosi'
anche i file gia' presenti nel repo non vengono scambiati per segnali veri.
"""


def has_momentum(entry: dict | None) -> bool:
    if not entry or entry.get("return_3m") is None:
        return False
    return not (entry["return_3m"] == 0.0 and entry.get("return_1m") == 0.0)


def has_fundamental(entry: dict | None) -> bool:
    if not entry or entry.get("f_score") is None:
        return False
    placeholder = (
        entry["f_score"] == 0.5
        and entry.get("pe_ratio") is None
        and entry.get("roe") is None
    )
    return not placeholder


def has_sentiment(entry: dict | None) -> bool:
    return bool(entry) and entry.get("num_articles", 0) > 0
