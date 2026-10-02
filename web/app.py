import json
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from flask import Flask, jsonify

from web.live_dashboard import build_live_html, load_all_portfolios
from web.price_cache import get_live_prices
from config import UNIVERSE  # Fixed: was incorrectly importing from main_pipeline
from dashboard_data import build_payload
from dashboard_generator import build_html
from price_history import load_price_history
from signals_utils import enrich_signals

app = Flask(__name__)

SIGNALS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "signals.json")


def _load_signals() -> dict:
    try:
        with open(SIGNALS_PATH, encoding="utf-8") as f:
            signals = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        signals = {}
    return enrich_signals(signals, UNIVERSE)


def _live_prices() -> dict:
    """Prezzi live (valuta locale); {} se il provider non risponde: la dashboard degrada."""
    try:
        prices = get_live_prices(list(UNIVERSE.keys()), ttl=60)
    except Exception:
        return {}
    return {t: p for t, p in prices.items() if p and p > 0}


@app.route("/")
def dashboard():
    """Dashboard interattiva (stessa di GitHub Pages) con prezzi live."""
    return build_html(load_all_portfolios(), _load_signals(), _live_prices())


@app.route("/api/data")
def api_data():
    """Payload JSON completo della dashboard."""
    payload = build_payload(
        load_all_portfolios(), _load_signals(), load_price_history(), _live_prices()
    )
    return jsonify(payload)


@app.route("/legacy")
def dashboard_legacy():
    """Vecchia dashboard con grafici matplotlib."""
    portfolios = load_all_portfolios()
    return build_live_html(portfolios, get_live_prices(list(UNIVERSE.keys()), ttl=60))


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
