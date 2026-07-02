"""
Interactive Brokers Client Portal REST API wrapper.

When IB_GATEWAY_URL and IB_ACCOUNT are set and the gateway is authenticated,
orders are placed as real market orders on the IB paper/demo account.
Falls back to simulation automatically if the gateway is unavailable.

Environment variables:
  IB_GATEWAY_URL   URL of the running Client Portal Gateway  (default: https://localhost:5000)
  IB_ACCOUNT       IB account ID, e.g. DU1234567           (required for live mode)
"""

import os
import urllib3
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# IB exchange identifiers for each exchange tag used in config.py
_EXCHANGE_MAP = {
    "NASDAQ": "SMART",
    "NYSE":   "SMART",
    "FTSE":   "LSE",   # London Stock Exchange (prices in GBp)
    "BIT":    "BVME",  # Borsa Italiana
}

# IB currency codes for each exchange
_CCY_MAP = {
    "NASDAQ": "USD",
    "NYSE":   "USD",
    "FTSE":   "GBP",
    "BIT":    "EUR",
}


def _strip_suffix(ticker: str) -> str:
    """ULVR.L → ULVR   ENI.MI → ENI   AAPL → AAPL"""
    return ticker.split(".")[0]


class IBBroker:
    """
    Thin wrapper around the IB Client Portal Gateway REST API.

    Usage:
        broker = IBBroker()
        if broker.is_available():
            broker.place_order("AAPL", "BUY", 1, "NASDAQ")
        broker.tickle()   # keep session alive (call every ~60 s)
    """

    def __init__(self) -> None:
        self.gateway_url = os.environ.get(
            "IB_GATEWAY_URL", "https://localhost:5000"
        ).rstrip("/")
        self.account = os.environ.get("IB_ACCOUNT", "")
        self._s = requests.Session()
        self._s.verify = False  # IB Gateway uses a self-signed TLS cert

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, **kw) -> dict | list:
        r = self._s.get(f"{self.gateway_url}{path}", timeout=10, **kw)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, **kw) -> dict | list:
        r = self._s.post(f"{self.gateway_url}{path}", timeout=15, **kw)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """True if the gateway is reachable AND the session is authenticated."""
        if not self.account:
            return False
        try:
            data = self._get("/v1/api/iserver/auth/status")
            return bool(data.get("authenticated"))
        except Exception:
            return False

    def tickle(self) -> None:
        """Ping the gateway to prevent session expiry (call every ~60 s)."""
        try:
            self._post("/v1/api/tickle")
        except Exception:
            pass

    def reauthenticate(self) -> bool:
        """Attempt silent reauthentication. Returns True on success."""
        try:
            self._post("/v1/api/iserver/reauthenticate")
            return self.is_available()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Contract lookup
    # ------------------------------------------------------------------

    def _get_conid(self, ticker: str, exchange_tag: str) -> int | None:
        """Resolve a ticker to an IB contract ID (conid)."""
        symbol = _strip_suffix(ticker)
        ib_exchange = _EXCHANGE_MAP.get(exchange_tag, "SMART")
        try:
            results = self._get(
                "/v1/api/iserver/secdef/search",
                params={"symbol": symbol, "secType": "STK"},
            )
            if not results:
                return None
            # Prefer a result whose listingExchange matches
            for r in results:
                if ib_exchange in r.get("description", "") or \
                   ib_exchange == r.get("listingExchange", ""):
                    return int(r["conid"])
            return int(results[0]["conid"])
        except Exception as e:
            print(f"[IB] conid lookup failed for {ticker}: {e}")
            return None

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def place_order(
        self,
        ticker: str,
        action: str,        # "BUY" or "SELL"
        quantity: int,
        exchange_tag: str,  # value from UNIVERSE[ticker]["exchange"]
    ) -> dict:
        """
        Submit a DAY market order to IB paper account.
        Returns the IB response dict, or {"error": "..."} on failure.

        Some orders require a confirmation; this method handles the first
        reply automatically.
        """
        conid = self._get_conid(ticker, exchange_tag)
        if not conid:
            return {"error": f"conid not found for {ticker}"}

        ccy = _CCY_MAP.get(exchange_tag, "USD")
        order_payload = {
            "orders": [
                {
                    "acctId": self.account,
                    "conid": conid,
                    "secType": f"{conid}:STK",
                    "orderType": "MKT",
                    "side": action.upper(),
                    "quantity": quantity,
                    "tif": "DAY",
                    "outsideRTH": False,
                    "ccy": ccy,
                }
            ]
        }

        try:
            result = self._post(
                f"/v1/api/iserver/account/{self.account}/orders",
                json=order_payload,
            )
            # IB may return a list with a "messageIds" / "id" reply request
            if isinstance(result, list):
                for item in result:
                    reply_id = item.get("id")
                    if reply_id:
                        result = self._post(
                            f"/v1/api/iserver/reply/{reply_id}",
                            json={"confirmed": True},
                        )
                        break
            print(f"[IB] {action} {quantity}x {ticker} → {result}")
            return result if isinstance(result, dict) else {"status": result}
        except Exception as e:
            print(f"[IB] Order failed for {ticker}: {e}")
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_price_history(self, ticker: str, exchange_tag: str) -> float | None:
        """
        Fetch the latest closing price via IB's marketdata/history endpoint.
        Returns the close price in the instrument's native currency
        (USD for NASDAQ/NYSE, GBp for LSE, EUR for BVME), or None on failure.
        """
        conid = self._get_conid(ticker, exchange_tag)
        if not conid:
            return None
        try:
            data = self._get(
                "/v1/api/iserver/marketdata/history",
                params={
                    "conid": conid,
                    "period": "1w",   # fetch 1 week so we always get at least one bar
                    "bar": "1d",
                    "outsideRth": True,
                },
            )
            bars = data.get("data", [])
            if not bars:
                print(f"[IB] no history bars for {ticker} (conid={conid})")
                return None
            close = float(bars[-1].get("c", 0))
            return close if close > 0 else None
        except Exception as e:
            print(f"[IB] price history failed for {ticker}: {e}")
            return None

    def get_market_prices(
        self, tickers_exchange: list[tuple[str, str]]
    ) -> dict[str, float]:
        """
        Fetch closing prices for a list of (ticker, exchange_tag) pairs.
        Returns {ticker: price_in_native_currency} for successfully fetched tickers.
        """
        prices: dict[str, float] = {}
        for ticker, exchange_tag in tickers_exchange:
            price = self.get_price_history(ticker, exchange_tag)
            if price is not None:
                prices[ticker] = price
                print(f"  {ticker}: {price:.4f} (ib_gateway)")
        return prices

    # ------------------------------------------------------------------
    # Position query
    # ------------------------------------------------------------------

    def get_positions(self) -> dict:
        """
        Return current IB positions as {ticker: {"shares": int, "avg_cost": float}}.
        avg_cost is in the position's native currency.
        """
        try:
            raw = self._get(f"/v1/api/portfolio/{self.account}/positions/0")
            out = {}
            for pos in raw:
                sym = pos.get("ticker") or pos.get("contractDesc", "")
                if sym:
                    out[sym] = {
                        "shares": int(pos.get("position", 0)),
                        "avg_cost": float(pos.get("avgCost", 0)),
                    }
            return out
        except Exception as e:
            print(f"[IB] get_positions failed: {e}")
            return {}


# Singleton for use across the pipeline
_broker: IBBroker | None = None


def get_broker() -> IBBroker:
    global _broker
    if _broker is None:
        _broker = IBBroker()
    return _broker
