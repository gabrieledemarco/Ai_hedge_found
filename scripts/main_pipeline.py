import argparse
import os
import math
from datetime import datetime, timezone

import pandas as pd
import requests
import yfinance as yf

from portfolio_io import load_portfolio, log_iteration
from telegram_utils import send_telegram_message, send_telegram_photo
from chart_utils import generate_dashboard

TIINGO_KEY = os.environ.get("TIINGO_API_KEY", "")
AV_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")

UNIVERSE = {
    "AAPL": {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "MSFT": {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "GOOGL": {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "AMZN": {"exchange": "NASDAQ", "currency": "USD", "sector": "Consumer"},
    "TSLA": {"exchange": "NASDAQ", "currency": "USD", "sector": "Auto"},
    "JPM": {"exchange": "NYSE", "currency": "USD", "sector": "Financial"},
    "NVDA": {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "JNJ": {"exchange": "NYSE", "currency": "USD", "sector": "Healthcare"},
    "V": {"exchange": "NYSE", "currency": "USD", "sector": "Financial"},
    "KO": {"exchange": "NYSE", "currency": "USD", "sector": "Consumer"},
    "ULVR.L": {"exchange": "FTSE", "currency": "GBP", "sector": "Consumer"},
    "HSBA.L": {"exchange": "FTSE", "currency": "GBP", "sector": "Financial"},
    "BP.L": {"exchange": "FTSE", "currency": "GBP", "sector": "Energy"},
    "GSK.L": {"exchange": "FTSE", "currency": "GBP", "sector": "Healthcare"},
    "RIO.L": {"exchange": "FTSE", "currency": "GBP", "sector": "Materials"},
    "ENI.MI": {"exchange": "BIT", "currency": "EUR", "sector": "Energy"},
    "ISP.MI": {"exchange": "BIT", "currency": "EUR", "sector": "Financial"},
    "ENEL.MI": {"exchange": "BIT", "currency": "EUR", "sector": "Utilities"},
    "LDO.MI": {"exchange": "BIT", "currency": "EUR", "sector": "Aerospace"},
    "MONC.MI": {"exchange": "BIT", "currency": "EUR", "sector": "Consumer"},
}


def fetch_prices(tickers: list[str]) -> tuple[dict[str, float], bool]:
    prices: dict[str, float] = {}
    all_real = True
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            hist = tk.history(period="1d")
            if hist.empty:
                hist = tk.history(period="5d")
            if not hist.empty:
                prices[t] = float(hist["Close"].iloc[-1])
                print(f"  {t}: {prices[t]:.2f} {UNIVERSE[t]['currency']} (yfinance)")
            else:
                fallback = 150.0 if t.endswith(".L") else 100.0
                print(f"[WARN] yfinance: no data for {t}, fallback {fallback}")
                prices[t] = fallback
                all_real = False
        except Exception as e:
            fallback = 150.0 if t.endswith(".L") else 100.0
            print(f"[WARN] yfinance failed for {t}: {e}, fallback {fallback}")
            prices[t] = fallback
            all_real = False
    return prices, all_real


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

    prices, all_prices_real = fetch_prices(tickers)
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

    if not all_prices_real:
        msg = (
            "ATTENZIONE: alcuni prezzi sono fallback (fonte yfinance non disponibile). "
            "Il trading è disabilitato fino a quando tutti i prezzi saranno reali. "
            "Solo report generato, nessuna transazione eseguita."
        )
        print(f"[WARN] {msg}")
        portfolio["metadata"]["price_source"] = "fallback"
        log_iteration(portfolio, session_label, portfolio_value_eur, [], prices, msg)
        send_telegram_message(
            f"FALLBACK: {session_label.upper()}\n{msg}\nNessun trade eseguito.",
            session=session_label,
            has_trades=False,
        )
        return portfolio_value_eur

    portfolio["metadata"]["price_source"] = "yfinance"

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

        price_local = prices.get(ticker, 0)
        currency = UNIVERSE[ticker]["currency"]
        price_eur = convert_to_eur(price_local, currency)
        diff_eur = target_eur - current_eur

        if weight_deviation < 0.05:
            reasoning_parts.append(
                f"{ticker}: HOLD (deviation {weight_deviation:.4f} < 0.05)"
            )
            continue

        if diff_eur > 0:
            if cash_eur <= 0:
                reasoning_parts.append(f"{ticker}: BUY skipped (no cash)")
                continue
            max_shares = math.floor(cash_eur / price_eur) if price_eur > 0 else 0
            if max_shares <= 0:
                reasoning_parts.append(
                    f"{ticker}: BUY skipped (1 share @ {price_eur:.2f}€ > cash {cash_eur:.2f}€)"
                )
                continue
            needed_shares = max(1, math.floor(diff_eur / price_eur))
            shares_to_trade = min(needed_shares, max_shares)
            cost = shares_to_trade * price_eur
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
            if entry["shares"] <= 0:
                reasoning_parts.append(f"{ticker}: HOLD (no shares to sell)")
                continue
            shares_to_sell = min(
                max(1, math.floor(abs(diff_eur) / price_eur)) if price_eur > 0 else 0,
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

    print("")
    print("--- TRANSAZIONI ---")
    if transactions:
        for t in transactions:
            print(f"  {t['action']} {t['shares']}x {t['ticker']}")
    else:
        print("  Nessuna transazione.")
    print("")
    print("--- REASONING ---")
    for line in reasoning_parts:
        print(f"  {line}")
    print("")

    report = build_telegram_report(
        session_label,
        total_value_eur,
        cash_eur,
        transactions,
        reasoning_parts,
        portfolio,
    )
    send_telegram_message(report, session=session_label, has_trades=has_trades)

    try:
        chart_path = generate_dashboard(portfolio, UNIVERSE, total_value_eur)
        send_telegram_photo(
            report[:500], chart_path, session=session_label, has_trades=has_trades
        )
    except Exception as e:
        print(f"[WARN] Chart generation/send failed: {e}")

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
    pos_count = len(portfolio["current_positions"])
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sep = "-" * 30
    lines = [
        "PAPER TRADING REPORT - {}".format(session.upper()),
        sep,
        "Portfolio: {:.2f} EUR".format(total_eur),
        "Cash: {:.2f} EUR".format(cash_eur),
        "Posizioni aperte: {}".format(pos_count),
        "",
    ]
    if transactions:
        lines.append("TRANSAZIONI:")
        for t in transactions:
            action = t["action"]
            shares = t["shares"]
            ticker = t["ticker"]
            price = t["price_eur"]
            if action == "BUY":
                lines.append(
                    "  {} {}x {} @ {:.2f}€ = {:.2f}€".format(
                        action, shares, ticker, price, t["total_cost_eur"]
                    )
                )
            else:
                lines.append(
                    "  {} {}x {} @ {:.2f}€ = +{:.2f}€".format(
                        action, shares, ticker, price, t["total_proceeds_eur"]
                    )
                )
    else:
        lines.append("Nessuna transazione eseguita.")
    lines.append("")
    lines.append("REASONING:")
    for r in reasoning:
        lines.append("  {}".format(r))
    lines.append("")
    lines.append("Aggiornato: {}".format(timestamp))
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
