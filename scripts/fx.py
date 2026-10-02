"""Tassi di cambio verso EUR con cache persistente.

Problema risolto: Alpha Vantage (piano gratuito) concede 25 richieste/giorno,
condivise con prezzi e sentiment. Finita la quota il codice usava tassi fissi
(USD 0.92) lontani da quelli reali, e il valore dei titoli USA oscillava di
qualche punto percentuale da una sessione all'altra.

Ora: un solo fetch per valuta al giorno (cache in data/fx_cache.json, versionata
dal workflow); se il fetch fallisce si usa l'ultimo tasso reale noto, e solo in
assenza di cache i tassi di ripiego di config.FX_FALLBACK.

Fonti, in ordine: Frankfurter (tassi BCE, gratuito e senza chiave ne' quota) e poi
Alpha Vantage (se c'e' la chiave), cosi' la quota di Alpha Vantage resta per i prezzi.
"""
import json
import os
from datetime import date

import requests

from config import FX_FALLBACK

FX_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "fx_cache.json")
MAX_JUMP = 0.25  # un tasso che si discosta di piu' del 25% dal riferimento e' un errore


def load_cache(path: str = FX_CACHE_PATH) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict, path: str = FX_CACHE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)
        f.write("\n")


def fetch_alpha_vantage_rate(base: str, quote: str, api_key: str) -> float | None:
    """Tasso live da Alpha Vantage, None se non disponibile (quota, rete, formato)."""
    try:
        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "CURRENCY_EXCHANGE_RATE",
                "from_currency": base,
                "to_currency": quote,
                "apikey": api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        rate = float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
        return rate if rate > 0 else None
    except (requests.RequestException, KeyError, ValueError, TypeError) as e:
        print(f"[WARN] FX fetch failed {base}->{quote}: {e}")
        return None


def fetch_frankfurter_rate(base: str, quote: str) -> float | None:
    """Tasso BCE da frankfurter.app (gratuito, senza chiave). None se non disponibile."""
    try:
        resp = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": base, "to": quote},
            timeout=15,
        )
        resp.raise_for_status()
        rate = float(resp.json()["rates"][quote])
        return rate if rate > 0 else None
    except (requests.RequestException, KeyError, ValueError, TypeError) as e:
        print(f"[WARN] Frankfurter FX failed {base}->{quote}: {e}")
        return None


def fetch_rate(base: str, quote: str, api_key: str = "") -> float | None:
    """Frankfurter prima, poi Alpha Vantage (solo se c'e' la chiave)."""
    rate = fetch_frankfurter_rate(base, quote)
    if rate is None and api_key:
        rate = fetch_alpha_vantage_rate(base, quote, api_key)
    return rate


def _plausible(rate: float, reference: float | None) -> bool:
    if not reference:
        return True
    return abs(rate / reference - 1.0) <= MAX_JUMP


def get_fx_rate(
    base: str,
    quote: str = "EUR",
    api_key: str = "",
    path: str = FX_CACHE_PATH,
    today: str | None = None,
    fetch=fetch_rate,
) -> float:
    if base == quote:
        return 1.0
    if base == "GBp":  # pence -> sterline
        return get_fx_rate("GBP", quote, api_key, path, today, fetch) / 100

    today = today or date.today().isoformat()
    cache = load_cache(path)
    cached = cache.get(base)

    if cached and cached.get("date") == today:
        return cached["rate"]  # gia' recuperato oggi: nessuna chiamata API

    reference = (cached or {}).get("rate") or FX_FALLBACK.get(base)
    rate = fetch(base, quote, api_key)
    if rate is not None and _plausible(rate, reference):
        cache[base] = {"rate": rate, "date": today}
        save_cache(cache, path)
        return rate
    if rate is not None:
        print(f"[WARN] FX {base}->{quote} = {rate} scartato (troppo lontano da {reference})")

    if cached:
        print(f"[WARN] FX {base}->{quote}: uso l'ultimo tasso noto ({cached['date']})")
        return cached["rate"]
    print(f"[WARN] FX {base}->{quote}: nessuna cache, uso il tasso di ripiego")
    return FX_FALLBACK.get(base, 1.0)
