import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask

from web.live_dashboard import load_portfolio, build_live_html
from web.price_cache import get_live_prices
from main_pipeline import UNIVERSE

app = Flask(__name__)


@app.route("/")
def dashboard():
    portfolio = load_portfolio()
    tickers = list(UNIVERSE.keys())
    live_prices = get_live_prices(tickers, ttl=60)
    html = build_live_html(portfolio, live_prices)
    return html


@app.route("/health")
def health():
    try:
        portfolio = load_portfolio()
        positions = len(portfolio.get("current_positions", {}))
        cash = portfolio["metadata"].get("current_cash", 0)
        last_log = portfolio.get("iterations_log", [])
        last_ts = last_log[-1]["timestamp"] if last_log else None
        return {
            "status": "ok",
            "service": "paper-trading-live",
            "positions": positions,
            "cash": cash,
            "last_update": last_ts,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
