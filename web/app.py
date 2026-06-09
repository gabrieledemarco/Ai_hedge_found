import os
import sys
import traceback

parent_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, parent_dir)
sys.path.insert(0, os.path.join(parent_dir, "scripts"))

from flask import Flask, jsonify

from web.live_dashboard import load_portfolio, build_live_html, get_portfolio_json
from web.price_cache import get_live_prices
from config import UNIVERSE

app = Flask(__name__)


@app.route("/")
def dashboard():
    try:
        portfolio = load_portfolio()
        tickers = list(UNIVERSE.keys())
        live_prices = get_live_prices(tickers, ttl=300)
        html = build_live_html(portfolio, live_prices)
        return html
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[FATAL] dashboard error: {e}")
        for line in tb.split("\n"):
            print(f"  {line}")
        return (
            f"<html><body style='background:#0f172a;color:#e2e8f0;padding:40px;font-family:sans-serif;'>"
            f"<h1>Paper Trading Dashboard</h1><p>Errore: {e}</p>"
            f"<pre style='font-size:11px;color:#94a3b8;margin-top:20px;'>{tb[:2000]}</pre>"
            f"</body></html>",
            200,
        )


@app.route("/api/portfolio")
def api_portfolio():
    try:
        portfolio = load_portfolio()
        tickers = list(UNIVERSE.keys())
        live_prices = get_live_prices(tickers, ttl=300)
        data = get_portfolio_json(portfolio, live_prices)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/prices")
def api_prices():
    try:
        tickers = list(UNIVERSE.keys())
        prices = get_live_prices(tickers, ttl=300)
        return jsonify(
            {
                "ts": [
                    {
                        "ticker": t,
                        "price": round(p, 4),
                        "ccy": UNIVERSE[t]["currency"],
                        "name": t,
                    }
                    for t, p in prices.items()
                ]
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chart/<ticker>")
def chart_view(ticker):
    ticker_upper = ticker.upper()
    if ticker_upper not in UNIVERSE:
        return f"<h3>Ticker {ticker_upper} sconosciuto</h3>", 404
    return f"""<!DOCTYPE html>
<html><head><title>{ticker_upper} Chart</title>
<style>body {{ margin:0; background:#0f172a; }}</style></head>
<body>
<!-- TradingView Widget BEGIN -->
<div class="tradingview-widget-container" style="height:100vh;width:100%;">
  <div id="tv-chart"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
  <script>
  new TradingView.widget({{
    "width": "100%", "height": "100%",
    "symbol": "{"NASDAQ:" if UNIVERSE[ticker_upper]["exchange"] == "NASDAQ" else "NYSE:" if UNIVERSE[ticker_upper]["exchange"] == "NYSE" else "LSE:" if UNIVERSE[ticker_upper]["exchange"] == "FTSE" else "MIL:"}{ticker_upper.replace(".MI", "").replace(".L", "")}",
    "interval": "D", "timezone": "Europe/Rome",
    "theme": "dark", "style": "1", "locale": "it",
    "toolbar_bg": "#1e293b", "enable_publishing": false,
    "hide_side_toolbar": false, "allow_symbol_change": true,
    "studies": ["RSI@tv-basicstudies","MASimple@tv-basicstudies","MACD@tv-basicstudies"]
  }});
  </script>
</div>
<!-- TradingView Widget END -->
</body></html>"""


@app.route("/screener")
def screener():
    return """<!DOCTYPE html>
<html><head><title>Stock Screener</title>
<style>body{margin:0;background:#0f172a;}</style></head>
<body>
<!-- TradingView Widget BEGIN -->
<div class="tradingview-widget-container" style="height:100vh;width:100%;">
  <div class="tradingview-widget-container__widget"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-screener.js" async>
  {
    "width": "100%", "height": "100%",
    "defaultColumn": "overview", "screener_type": "stock_market",
    "displayCurrency": "EUR", "colorTheme": "dark",
    "locale": "it", "market": "global"
  }
  </script>
</div>
<!-- TradingView Widget END -->
</body></html>"""


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
