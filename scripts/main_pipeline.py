import argparse
import os
import math
from datetime import datetime, timezone

import pandas as pd
import requests

from portfolio_io import load_portfolio, log_iteration
from telegram_utils import send_telegram_message, h

TIINGO_KEY = os.environ.get("TIINGO_API_KEY", "")
AV_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")

UNIVERSE = {
    "AAPL": {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "MSFT": {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "GOOGL": {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "AMZN": {"exchange": "NASDAQ", "currency": "USD", "sector": "Consumer"},
    "TSLA": {"exchange": "NASDAQ", "currency": "USD", "sector": "Auto"},
    "JPM": {"exchange": "NYSE", "currency": "USD", "sector": "Financial"},
    "BRK.B": {"exchange": "NYSE", "currency": "USD", "sector": "Financial"},
    "JNJ": {"exchange": "NYSE", "currency": "USD", "sector": "Healthcare"},
    "V": {"exchange": "NYSE", "currency": "USD", "sector": "Financial"},
    "KO": {"exchange": "NYSE", "currency": "USD", "sector": "Consumer"},
    "ULVR.L": {"exchange": "FTSE", "currency": "GBP", "sector": "Consumer"},
    "HSBA.L": {"exchange": "FTSE", "currency": "GBP", "sector": "Financial"},
    "BP.L": {"exchange": "FTSE", "currency": "GBP", "sector": "Energy"},
    "GSK.L": {"exchange": "FTSE", "currency": "GBP", "sector": "Healthcare"},
    "RIO.L": {"exchange": "FTSE", "currency": "GBP", "sector": "Materials"},
}


def _tiingo_symbol(ticker: str) -> str:
    if ticker.endswith(".L"):
        return ""
    sym = ticker.replace(".B", "-B").replace(".", "-")
    return sym


def _alpha_vantage_symbol(ticker: str) -> str:
    if ticker.endswith(".L"):
        return ticker.replace(".L", ".LON")
    return ticker


def fetch_price_tiingo(ticker: str) -> float | None:
    symbol = _tiingo_symbol(ticker)
    if not symbol:
        return None
    url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices"
    params = {"token": TIINGO_KEY, "resampleFreq": "daily"}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data:
            return float(data[-1]["adjClose"])
        print(f"[WARN] Tiingo: no price data for {ticker} ({symbol})")
    except requests.RequestException as e:
        print(f"[WARN] Tiingo failed for {ticker} ({symbol}): {e}")
    return None


def fetch_price_alphavantage(ticker: str) -> float | None:
    symbol = _alpha_vantage_symbol(ticker)
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "apikey": AV_KEY,
        "outputsize": "compact",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        key = "Time Series (Daily)"
        if key in data:
            dates = sorted(data[key].keys(), reverse=True)
            if dates:
                return float(data[key][dates[0]]["4. close"])
        print(f"[WARN] Alpha Vantage: no data for {ticker} ({symbol})")
    except requests.RequestException as e:
        print(f"[WARN] Alpha Vantage failed for {ticker} ({symbol}): {e}")
    return None


def fetch_prices(tickers: list[str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for t in tickers:
        price = fetch_price_tiingo(t)
        if price is not None:
            prices[t] = price
            continue
        price = fetch_price_alphavantage(t)
        if price is not None:
            prices[t] = price
            continue
        fallback = 150.0 if t.endswith(".L") else 100.0
        print(f"[WARN] {t}: nessun prezzo da fonti primarie, uso fallback {fallback}")
        prices[t] = fallback
    return prices


def fetch_fx_rate(base: str, quote: str = "EUR") -> float:
    if base == quote:
        return 1.0
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "CURRENCY_EXCHANGE_RATE",
        "from_currency": base,
        "to_currency": quote,
        "apikey": AV_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        key = "Realtime Currency Exchange Rate"
        if key in data:
            return float(data[key]["5. Exchange Rate"])
    except (requests.RequestException, KeyError, ValueError, TypeError) as e:
        print(f"[WARN] FX fetch failed {base}->{quote}: {e}. Using fallback.")
    fallback_rates = {"USD": 0.92, "GBP": 1.17}
    return fallback_rates.get(base, 1.0)


def convert_to_eur(amount: float, currency: str) -> float:
    rate = fetch_fx_rate(currency, "EUR")
    return amount * rate


def calculate_targets(
    total_capital_eur: float,
) -> dict[str, float]:
    num_assets = len(UNIVERSE)
    target_weight = 1.0 / num_assets
    return {ticker: total_capital_eur * target_weight for ticker in UNIVERSE}


def validate_env() -> bool:
    checks = [
        ("TIINGO_API_KEY", TIINGO_KEY, "Prezzi azionari (Tiingo)"),
        ("ALPHA_VANTAGE_KEY", AV_KEY, "Tassi FX (Alpha Vantage)"),
        ("TELEGRAM_TOKEN", os.environ.get("TELEGRAM_TOKEN", ""), "Bot Telegram"),
        ("TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", ""), "Chat Telegram"),
    ]
    all_ok = True
    for name, val, label in checks:
        if not val:
            print(f"[WARN] {name} non impostata — {label} userà dati di fallback")
            all_ok = False
    if not all_ok:
        print(
            "[WARN] Imposta i GitHub Secrets: Settings → Secrets and variables → Actions"
        )
    return all_ok


def run_pipeline(session_label: str) -> None:
    print(
        f"=== Paper Trading Pipeline | Session: {session_label} | {datetime.now(timezone.utc).isoformat()} ==="
    )
    validate_env()
    portfolio = load_portfolio()
    tickers = list(UNIVERSE.keys())

    prices = fetch_prices(tickers)
    fx_rates = {}
    currencies_used = set(info["currency"] for info in UNIVERSE.values())
    for c in currencies_used:
        fx_rates[c] = fetch_fx_rate(c, "EUR")
        print(f"  FX {c}/EUR = {fx_rates[c]:.4f}")

    portfolio_value_eur = 0.0
    position_values_eur = {}
    for ticker in tickers:
        price_local = prices.get(ticker, 0)
        currency = UNIVERSE[ticker]["currency"]
        price_eur = convert_to_eur(price_local, currency)
        shares = portfolio["current_positions"].get(ticker, {}).get("shares", 0)
        pos_val_eur = price_eur * shares
        position_values_eur[ticker] = pos_val_eur
        portfolio_value_eur += pos_val_eur

    cash_eur = portfolio["metadata"]["current_cash"]
    portfolio_value_eur += cash_eur
    print(f"  Portfolio total (incl. cash): {portfolio_value_eur:.2f} EUR")
    print(f"  Cash: {cash_eur:.2f} EUR")

    targets_eur = calculate_targets(portfolio_value_eur)
    transactions: list[dict] = []
    reasoning_parts = []
    has_trades = False

    for ticker in tickers:
        target_eur = targets_eur[ticker]
        current_eur = position_values_eur[ticker]
        weight_deviation = (
            abs(target_eur - current_eur) / portfolio_value_eur
            if portfolio_value_eur > 0
            else 0
        )

        if weight_deviation < 0.05:
            reasoning_parts.append(
                f"{ticker}: HOLD (deviation {weight_deviation:.4f} < 0.05)"
            )
            continue

        price_local = prices.get(ticker, 0)
        currency = UNIVERSE[ticker]["currency"]
        price_eur = convert_to_eur(price_local, currency)
        diff_eur = target_eur - current_eur

        if diff_eur > 0 and cash_eur <= 0:
            reasoning_parts.append(f"{ticker}: BUY skipped (no cash)")
            continue

        if diff_eur > 0:
            max_shares = math.floor(cash_eur / price_eur) if price_eur > 0 else 0
            needed_shares = math.floor(diff_eur / price_eur) if price_eur > 0 else 0
            shares_to_trade = min(needed_shares, max_shares)
            if shares_to_trade <= 0:
                reasoning_parts.append(f"{ticker}: BUY skipped (lot < 1 share)")
                continue
            cost = shares_to_trade * price_eur
            if cost > cash_eur:
                reasoning_parts.append(
                    f"{ticker}: BUY skipped (insufficient cash after lot check)"
                )
                continue
            entry = portfolio["current_positions"].get(
                ticker, {"shares": 0, "avg_price": 0.0}
            )
            total_shares = entry["shares"] + shares_to_trade
            total_cost = entry["avg_price"] * entry["shares"] + cost
            portfolio["current_positions"][ticker] = {
                "shares": total_shares,
                "avg_price": round(total_cost / total_shares, 4)
                if total_shares > 0
                else 0,
            }
            cash_eur -= cost
            portfolio["metadata"]["current_cash"] = round(cash_eur, 2)
            transactions.append(
                {
                    "action": "BUY",
                    "ticker": ticker,
                    "shares": shares_to_trade,
                    "price_eur": round(price_eur, 4),
                    "total_cost_eur": round(cost, 2),
                }
            )
            reasoning_parts.append(
                f"{ticker}: BUY {shares_to_trade} @ {price_eur:.2f}€ "
                f"(deviation {weight_deviation:.4f})"
            )
            has_trades = True
        elif diff_eur < 0:
            entry = portfolio["current_positions"].get(ticker, {"shares": 0})
            shares_to_sell = min(
                math.floor(abs(diff_eur) / price_eur) if price_eur > 0 else 0,
                entry["shares"],
            )
            if shares_to_sell <= 0:
                reasoning_parts.append(f"{ticker}: SELL skipped (lot < 1 share)")
                continue
            proceeds = shares_to_sell * price_eur
            portfolio["current_positions"][ticker]["shares"] -= shares_to_sell
            if portfolio["current_positions"][ticker]["shares"] <= 0:
                del portfolio["current_positions"][ticker]
            cash_eur += proceeds
            portfolio["metadata"]["current_cash"] = round(cash_eur, 2)
            transactions.append(
                {
                    "action": "SELL",
                    "ticker": ticker,
                    "shares": shares_to_sell,
                    "price_eur": round(price_eur, 4),
                    "total_proceeds_eur": round(proceeds, 2),
                }
            )
            reasoning_parts.append(
                f"{ticker}: SELL {shares_to_sell} @ {price_eur:.2f}€ "
                f"(deviation {weight_deviation:.4f})"
            )
            has_trades = True
        else:
            reasoning_parts.append(f"{ticker}: HOLD (on target)")

    cash_eur = portfolio["metadata"]["current_cash"]
    total_value_eur = cash_eur + sum(
        convert_to_eur(
            prices.get(t, 0)
            * portfolio["current_positions"].get(t, {}).get("shares", 0),
            UNIVERSE[t]["currency"],
        )
        for t in tickers
    )

    reasoning = "\n".join(reasoning_parts)
    log_iteration(
        portfolio, session_label, total_value_eur, transactions, prices, reasoning
    )

    report = build_telegram_report(
        session_label,
        total_value_eur,
        cash_eur,
        transactions,
        reasoning_parts,
        portfolio,
    )
    send_telegram_message(report, session=session_label, has_trades=has_trades)

    print(f"[DONE] Session {session_label} completed. Total: {total_value_eur:.2f} EUR")
    return total_value_eur


def build_telegram_report(
    session: str,
    total_eur: float,
    cash_eur: float,
    transactions: list[dict],
    reasoning: list[str],
    portfolio: dict,
) -> str:
    lines = [
        f"<b>Paper Trading Report \u2014 {h(session.upper())}</b>",
        f"Portfolio: {h(f'{total_eur:.2f}')} EUR",
        f"Cash: {h(f'{cash_eur:.2f}')} EUR",
        f"Positions: {h(str(len(portfolio['current_positions'])))}",
        "",
    ]
    if transactions:
        lines.append("<b>Transazioni:</b>")
        for t in transactions:
            action = t["action"]
            if action == "BUY":
                lines.append(
                    f"  {h(action)} {h(str(t['shares']))}x {h(t['ticker'])} @ {h(f'{t['price_eur']:.2f}')}\u20ac"
                    f" = {h(f'{t['total_cost_eur']:.2f}')}\u20ac"
                )
            else:
                lines.append(
                    f"  {h(action)} {h(str(t['shares']))}x {h(t['ticker'])} @ {h(f'{t['price_eur']:.2f}')}\u20ac"
                    f" = +{h(f'{t['total_proceeds_eur']:.2f}')}\u20ac"
                )
    else:
        lines.append("<i>Nessuna transazione eseguita.</i>")
    lines.append("")
    lines.append("<b>Reasoning:</b>")
    for r in reasoning:
        lines.append(f"  {h(r)}")
    lines.append("")
    lines.append(
        f"<i>Aggiornato: {h(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))}</i>"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paper Trading Pipeline")
    parser.add_argument(
        "--hour", type=int, required=True, help="Esecuzione hour in UTC (7, 15, 21)"
    )
    args = parser.parse_args()

    hour_map = {7: "mattina", 15: "pomeriggio", 21: "sera"}
    label = hour_map.get(args.hour)
    if label is None:
        raise SystemExit(
            f"ERROR: --hour {args.hour} non valido. Usa 7 (mattina), 15 (pomeriggio), 21 (sera)."
        )

    run_pipeline(label)
