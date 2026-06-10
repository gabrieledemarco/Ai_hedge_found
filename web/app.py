import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from flask import Flask, jsonify

from web.live_dashboard import build_live_html, load_all_portfolios
from web.price_cache import get_live_prices
from config import UNIVERSE  # Fixed: was incorrectly importing from main_pipeline

app = Flask(__name__)


@app.route("/")
def dashboard():
    tickers = list(UNIVERSE.keys())
    live_prices = get_live_prices(tickers, ttl=60)
    portfolios = load_all_portfolios()
    return build_live_html(portfolios, live_prices)


@app.route("/api/prices")
def api_prices():
    """Live EUR prices for all 20 tickers. Cached 60s."""
    tickers = list(UNIVERSE.keys())
    return jsonify(get_live_prices(tickers, ttl=60))


@app.route("/api/portfolios")
def api_portfolios():
    """Summary of all 4 strategy portfolios (cash, positions, last update)."""
    portfolios = load_all_portfolios()
    return jsonify({
        name: {
            "cash": p["metadata"].get("current_cash", 0),
            "initial_capital": p["metadata"].get("initial_capital", 3000.0),
            "positions": len(p.get("current_positions", {})),
            "last_update": (p.get("iterations_log") or [{}])[-1].get("timestamp"),
            "iterations": len(p.get("iterations_log", [])),
        }
        for name, p in portfolios.items()
    })


@app.route("/health")
def health():
    try:
        portfolios = load_all_portfolios()
        strategies_status = {}
        for name, p in portfolios.items():
            logs = p.get("iterations_log", [])
            strategies_status[name] = {
                "positions": len(p.get("current_positions", {})),
                "cash": round(p["metadata"].get("current_cash", 0), 2),
                "last_update": logs[-1]["timestamp"] if logs else None,
            }
        return jsonify({
            "status": "ok",
            "service": "ai-hedge-fund-live",
            "strategies": strategies_status,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
