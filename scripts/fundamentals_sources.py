"""
Fonti dei dati fondamentali e logica di aggiornamento (cache + rotazione della quota).

Problema: Yahoo Finance blocca le richieste da GitHub Actions, quindi `info` torna vuoto e la
strategia Fundamental restava senza dati veri. Qui:

  * la fonte primaria resta Yahoo (funziona in locale, anche per FTSE e Borsa Italiana);
  * quando Yahoo non risponde si ripiega su Alpha Vantage `OVERVIEW` (P/E e ROE; niente FCF
    ne' debito/equity, quindi lo score usa meno metriche), con una quota giornaliera
    limitata perche' il piano gratuito concede 25 richieste/giorno condivise con prezzi e
    sentiment;
  * ogni voce porta `fetched_at` e `source`: i fondamentali cambiano ogni trimestre, quindi
    una voce fresca (< `max_age_days`) non viene richiesta di nuovo, e le richieste vanno
    prima ai titoli senza dato e poi ai piu' vecchi (rotazione).
"""
import os
from datetime import datetime, timedelta, timezone

import requests

from strategies.signal_utils import has_fundamental

AV_URL = "https://www.alphavantage.co/query"
DEFAULT_MAX_AGE_DAYS = 14
DEFAULT_AV_BUDGET = 5  # richieste Alpha Vantage per esecuzione (quota giornaliera: 25)


class QuotaExceeded(Exception):
    """Alpha Vantage ha risposto con il messaggio di quota/limite di frequenza."""


def av_symbol(ticker: str) -> str:
    """Simbolo Alpha Vantage per i ticker europei (ENI.MI -> ENI.MIL, ULVR.L -> ULVR.LON)."""
    return ticker.replace(".MI", ".MIL").replace(".L", ".LON")


def _num(value) -> float | None:
    """Alpha Vantage restituisce stringhe, e "None" quando il dato manca."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_alpha_vantage_overview(ticker: str, api_key: str) -> dict | None:
    """Metriche fondamentali da Alpha Vantage, con le stesse chiavi di yfinance `info`.

    Ritorna None se il titolo non e' coperto; solleva QuotaExceeded se la quota e' finita.
    """
    resp = requests.get(
        AV_URL,
        params={"function": "OVERVIEW", "symbol": av_symbol(ticker), "apikey": api_key},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or not data:
        return None
    if "Note" in data or "Information" in data:
        raise QuotaExceeded(str(data.get("Note") or data.get("Information"))[:120])
    if "Symbol" not in data:
        return None

    info: dict = {}
    pe = _num(data.get("TrailingPE")) or _num(data.get("PERatio"))
    if pe and pe > 0:
        info["trailingPE"] = pe
    roe = _num(data.get("ReturnOnEquityTTM"))
    if roe is not None:
        info["returnOnEquity"] = roe
    for av_key, key in (
        ("MarketCapitalization", "marketCap"),
        ("PriceToBookRatio", "priceToBook"),
        ("QuarterlyRevenueGrowthYOY", "revenueGrowth"),
    ):
        value = _num(data.get(av_key))
        if value is not None:
            info[key] = value
    # Senza P/E ne' ROE lo score non avrebbe nessuna base: meglio nessun dato.
    return info if ("trailingPE" in info or "returnOnEquity" in info) else None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def needs_refresh(
    entry: dict | None, now: datetime, max_age_days: int = DEFAULT_MAX_AGE_DAYS
) -> bool:
    """True se manca un dato reale o se e' piu' vecchio di `max_age_days`."""
    if not has_fundamental(entry):
        return True
    fetched = _parse_ts(entry.get("fetched_at"))
    if fetched is None:  # dato reale ma senza data: si riscarica per datarlo
        return True
    return now - fetched > timedelta(days=max_age_days)


def plan_refresh(
    universe: dict,
    previous: dict,
    now: datetime,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    force: bool = False,
) -> list[str]:
    """Ticker da aggiornare, nell'ordine: prima senza dato reale, poi dal piu' vecchio."""
    due = [t for t in universe if force or needs_refresh(previous.get(t), now, max_age_days)]

    def age_key(ticker: str):
        entry = previous.get(ticker)
        if not has_fundamental(entry):
            return (0, "")
        return (1, entry.get("fetched_at") or "")

    return sorted(due, key=age_key)


def av_budget_from_env() -> int:
    try:
        return max(0, int(os.environ.get("AV_FUNDAMENTALS_PER_RUN", DEFAULT_AV_BUDGET)))
    except ValueError:
        return DEFAULT_AV_BUDGET
