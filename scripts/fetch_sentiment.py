import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone

AV_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")


def fetch_av_news_sentiment(ticker: str) -> dict:
    """
    Calls Alpha Vantage NEWS_SENTIMENT for a ticker.
    Rate limit: 5 req/min on free tier -> sleep 13s between requests.
    Returns: {"score": float[-1,1], "label": str, "num_articles": int, "headlines": list}
    """
    if not AV_KEY:
        return {"score": 0.0, "label": "neutral", "num_articles": 0, "headlines": []}

    url = "https://www.alphavantage.co/query"
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "apikey": AV_KEY,
        "limit": "10",
        "sort": "LATEST",
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("feed", [])

        headlines = []
        av_scores = []
        for article in articles:
            headlines.append(article.get("title", ""))
            for ts in article.get("ticker_sentiment", []):
                if ts.get("ticker") == ticker:
                    try:
                        av_scores.append(float(ts["ticker_sentiment_score"]))
                    except (ValueError, KeyError):
                        pass

        if not av_scores:
            return {
                "score": 0.0,
                "label": "neutral",
                "num_articles": 0,
                "headlines": headlines,
            }

        avg_score = sum(av_scores) / len(av_scores)
        label = (
            "Bullish"
            if avg_score > 0.1
            else ("Bearish" if avg_score < -0.1 else "Neutral")
        )
        return {
            "score": round(avg_score, 4),
            "label": label,
            "num_articles": len(av_scores),
            "headlines": headlines[:5],
        }
    except Exception as e:
        print(f"[WARN] AV sentiment failed for {ticker}: {e}")
        return {"score": 0.0, "label": "neutral", "num_articles": 0, "headlines": []}


_FINBERT = None


def _get_finbert():
    """Carica FinBERT una sola volta per processo (prima veniva ricaricato, ~400 MB,
    per ognuno dei 20 ticker)."""
    global _FINBERT
    if _FINBERT is None:
        from transformers import pipeline as hf_pipeline

        print("[INFO] Loading FinBERT model...")
        _FINBERT = hf_pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            truncation=True,
            max_length=512,
            device=-1,  # CPU
        )
    return _FINBERT


def run_finbert_on_headlines(headlines: list) -> float:
    """
    Run FinBERT on a list of headlines. Returns mean score in [-1, 1].
    Lazy-loads the model once (only if called).
    Returns 0.0 if no headlines or if transformers is not available.
    """
    if not headlines:
        return 0.0
    try:
        finbert = _get_finbert()
        scores = []
        for headline in headlines:
            if not headline.strip():
                continue
            try:
                result = finbert(headline[:512])[0]
                label = result["label"].lower()
                conf = result["score"]
                if label == "positive":
                    scores.append(conf)
                elif label == "negative":
                    scores.append(-conf)
                else:
                    scores.append(0.0)
            except Exception as e:
                print(f"[WARN] FinBERT inference failed on a headline: {e}")
        return round(sum(scores) / len(scores), 4) if scores else 0.0
    except ImportError:
        print("[WARN] transformers not installed, skipping FinBERT")
        return 0.0
    except Exception as e:
        print(f"[WARN] FinBERT failed: {e}")
        return 0.0


RECHECK_DAYS = 7


def _recently_empty(previous: dict, now: datetime, recheck_days: int) -> bool:
    """True se un controllo recente ha dato 0 articoli: inutile sprecare una delle
    25 richieste giornaliere di Alpha Vantage per richiederlo ogni giorno."""
    if not previous or previous.get("num_articles", 0) > 0:
        return False
    checked = previous.get("checked_at")
    if not checked:
        return False  # voce vecchia senza data: ricontrolla e metti il timbro
    try:
        when = datetime.fromisoformat(checked)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return now - when < timedelta(days=recheck_days)


def fetch_all_sentiment(
    universe: dict,
    previous: dict | None = None,
    recheck_days: int = RECHECK_DAYS,
    now: datetime | None = None,
) -> dict:
    """
    Fetch sentiment for all tickers in universe.
    Combines Alpha Vantage score (70%) + FinBERT score (30%) if headlines available.
    Respects AV rate limit: 13s sleep between requests.

    I ticker che nell'ultimo controllo (entro `recheck_days`) non avevano articoli
    non vengono richiesti di nuovo: con i titoli europei non coperti da Alpha
    Vantage si risparmiano ~10 delle 25 richieste giornaliere.
    """
    previous = previous or {}
    now = now or datetime.now(timezone.utc)
    results = {}
    tickers = list(universe.keys())

    print(f"[INFO] Fetching sentiment for {len(tickers)} tickers...")
    called = 0
    for i, ticker in enumerate(tickers):
        prev = previous.get(ticker)
        if _recently_empty(prev, now, recheck_days):
            print(f"  [{i+1}/{len(tickers)}] {ticker}: nessun articolo di recente, salto")
            results[ticker] = prev
            continue

        print(f"  [{i+1}/{len(tickers)}] {ticker}...")
        if called:
            time.sleep(13)  # 5 req/min sul piano gratuito AV
        called += 1
        av_data = fetch_av_news_sentiment(ticker)

        # Combine AV score with FinBERT
        finbert_score = 0.0
        if av_data["headlines"]:
            finbert_score = run_finbert_on_headlines(av_data["headlines"])

        # Weighted combination
        if av_data["num_articles"] > 0 and finbert_score != 0.0:
            combined = 0.7 * av_data["score"] + 0.3 * finbert_score
        elif av_data["num_articles"] > 0:
            combined = av_data["score"]
        else:
            combined = finbert_score

        results[ticker] = {
            "score": round(combined, 4),
            "av_score": av_data["score"],
            "finbert_score": finbert_score,
            "label": av_data["label"],
            "num_articles": av_data["num_articles"],
            "checked_at": now.isoformat(),
        }

    return results


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(__file__))
    from config import UNIVERSE

    signals_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "signals.json"
    )
    try:
        with open(signals_path) as f:
            signals = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        signals = {}

    sentiment = fetch_all_sentiment(UNIVERSE, previous=signals.get("sentiment"))

    signals["sentiment"] = sentiment
    signals["sentiment_updated"] = datetime.now(timezone.utc).isoformat()

    with open(signals_path, "w") as f:
        json.dump(signals, f, indent=2)

    print(f"[OK] Sentiment saved to {signals_path}")
