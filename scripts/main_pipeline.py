import argparse
import os
import sys
import math
import json
from datetime import datetime, timezone

import requests
import yfinance as yf

# Ensure scripts/ directory is on the path so config and strategies are importable
sys.path.insert(0, os.path.dirname(__file__))

from config import UNIVERSE, STRATEGIES, INITIAL_CAPITAL, REBALANCE_THRESHOLD
from portfolio_io import (
    load_portfolio,
    log_iteration,
    load_portfolio_for_strategy,
    log_iteration_for_strategy,
)
from telegram_utils import send_telegram_message, send_telegram_photo
from chart_utils import generate_dashboard
from dashboard_generator import build_html

from strategies import (
    EqualWeightStrategy,
    MomentumStrategy,
    FundamentalStrategy,
    SentimentStrategy,
)

AV_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")

STRATEGY_INSTANCES = {
    "equal_weight": EqualWeightStrategy(),
    "momentum": MomentumStrategy(),
    "fundamental": FundamentalStrategy(),
    "sentiment": SentimentStrategy(),
}


# ---------------------------------------------------------------------------
# Price / FX helpers
# ---------------------------------------------------------------------------

def fetch_prices(tickers: list) -> tuple:
    prices: dict = {}
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


def convert_to_eur(amount: float, currency: str, fx_rates: dict = None) -> float:
    if fx_rates and currency in fx_rates:
        return amount * fx_rates[currency]
    return amount * fetch_fx_rate(currency, "EUR")


def validate_env() -> bool:
    checks = [
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
        print("[WARN] Imposta i GitHub Secrets: Settings → Secrets and variables → Actions")
    return all_ok


def load_signals() -> dict:
    """Load signals.json, return empty dict if missing/invalid."""
    signals_path = os.path.join(os.path.dirname(__file__), "..", "data", "signals.json")
    try:
        with open(signals_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Single-strategy pipeline
# ---------------------------------------------------------------------------

def run_strategy_pipeline(
    strategy_name: str,
    session_label: str,
    prices: dict,
    fx_rates: dict,
    signals: dict,
    all_prices_real: bool,
) -> dict:
    """
    Run the trading pipeline for one strategy.
    Returns {total_value_eur, cash_eur, transactions, reasoning_parts, portfolio}.
    """
    strategy = STRATEGY_INSTANCES[strategy_name]
    portfolio = load_portfolio_for_strategy(strategy_name)
    tickers = list(UNIVERSE.keys())

    # --- Compute portfolio value ---
    portfolio_value_eur = 0.0
    position_values_eur = {}
    for ticker in tickers:
        price_local = prices.get(ticker, 0)
        currency = UNIVERSE[ticker]["currency"]
        price_eur = price_local * fx_rates.get(currency, 1.0)
        shares = portfolio["current_positions"].get(ticker, {}).get("shares", 0)
        pos_val_eur = price_eur * shares
        position_values_eur[ticker] = pos_val_eur
        portfolio_value_eur += pos_val_eur

    cash_eur = portfolio["metadata"]["current_cash"]
    portfolio_value_eur += cash_eur

    if not all_prices_real:
        msg = (
            "ATTENZIONE: alcuni prezzi sono fallback. "
            "Trading disabilitato, solo report."
        )
        portfolio["metadata"]["price_source"] = "fallback"
        log_iteration_for_strategy(
            strategy_name, portfolio, session_label, portfolio_value_eur, [], prices, msg
        )
        return {
            "total_value_eur": portfolio_value_eur,
            "cash_eur": cash_eur,
            "transactions": [],
            "reasoning_parts": [msg],
            "portfolio": portfolio,
            "has_trades": False,
        }

    portfolio["metadata"]["price_source"] = "yfinance"

    # --- Compute target weights from strategy ---
    weights = strategy.compute_weights(UNIVERSE, prices, signals)

    transactions = []
    reasoning_parts = []
    has_trades = False

    for ticker in tickers:
        target_weight = weights.get(ticker, 0.0)
        target_eur = portfolio_value_eur * target_weight
        current_eur = position_values_eur.get(ticker, 0.0)
        weight_deviation = (
            abs(target_eur - current_eur) / portfolio_value_eur
            if portfolio_value_eur > 0
            else 0
        )

        price_local = prices.get(ticker, 0)
        currency = UNIVERSE[ticker]["currency"]
        price_eur = price_local * fx_rates.get(currency, 1.0)
        diff_eur = target_eur - current_eur

        if weight_deviation < REBALANCE_THRESHOLD:
            reasoning_parts.append(
                f"{ticker}: HOLD (deviation {weight_deviation:.4f} < {REBALANCE_THRESHOLD})"
            )
            continue

        if diff_eur > 0:
            if cash_eur <= 0:
                reasoning_parts.append(f"{ticker}: BUY skipped (no cash)")
                continue
            if price_eur <= 0:
                reasoning_parts.append(f"{ticker}: BUY skipped (price=0)")
                continue
            max_shares = math.floor(cash_eur / price_eur)
            if max_shares <= 0:
                reasoning_parts.append(
                    f"{ticker}: BUY skipped (1 share @ {price_eur:.2f}EUR > cash {cash_eur:.2f}EUR)"
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
                "avg_price": round(total_cost / total_shares, 4) if total_shares > 0 else 0,
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
                f"{ticker}: BUY {shares_to_trade} @ {price_eur:.2f}EUR "
                f"(deviation {weight_deviation:.4f}, weight {target_weight:.3f})"
            )
            has_trades = True

        elif diff_eur < 0:
            entry = portfolio["current_positions"].get(ticker, {"shares": 0})
            if entry["shares"] <= 0:
                reasoning_parts.append(f"{ticker}: HOLD (no shares to sell)")
                continue
            if price_eur <= 0:
                reasoning_parts.append(f"{ticker}: SELL skipped (price=0)")
                continue
            shares_to_sell = min(
                max(1, math.floor(abs(diff_eur) / price_eur)),
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
                f"{ticker}: SELL {shares_to_sell} @ {price_eur:.2f}EUR "
                f"(deviation {weight_deviation:.4f}, weight {target_weight:.3f})"
            )
            has_trades = True
        else:
            reasoning_parts.append(f"{ticker}: HOLD (on target)")

    # Recalculate total after trades
    cash_eur = portfolio["metadata"]["current_cash"]
    total_value_eur = cash_eur + sum(
        prices.get(t, 0)
        * fx_rates.get(UNIVERSE[t]["currency"], 1.0)
        * portfolio["current_positions"].get(t, {}).get("shares", 0)
        for t in tickers
    )

    reasoning = "\n".join(reasoning_parts)
    log_iteration_for_strategy(
        strategy_name, portfolio, session_label, total_value_eur, transactions, prices, reasoning
    )

    return {
        "total_value_eur": total_value_eur,
        "cash_eur": cash_eur,
        "transactions": transactions,
        "reasoning_parts": reasoning_parts,
        "portfolio": portfolio,
        "has_trades": has_trades,
    }


# ---------------------------------------------------------------------------
# Multi-strategy orchestrator
# ---------------------------------------------------------------------------

def run_pipeline(session_label: str) -> float:
    print(
        f"=== AI Hedge Fund Multi-Strategy Pipeline | "
        f"Session: {session_label} | {datetime.now(timezone.utc).isoformat()} ==="
    )
    validate_env()
    tickers = list(UNIVERSE.keys())

    # Fetch prices once (shared across all strategies)
    print("[INFO] Fetching prices...")
    prices, all_prices_real = fetch_prices(tickers)

    # Fetch FX rates once
    fx_rates = {}
    currencies_used = set(info["currency"] for info in UNIVERSE.values())
    for c in currencies_used:
        if c != "EUR":
            fx_rates[c] = fetch_fx_rate(c, "EUR")
        else:
            fx_rates[c] = 1.0
        print(f"  FX {c}/EUR = {fx_rates[c]:.4f}")

    # Load signals (may be empty if market_analysis hasn't run yet)
    signals = load_signals()
    print(f"[INFO] Signals loaded — keys: {list(signals.keys())}")

    # --- Run each strategy ---
    strategy_results = {}
    for strategy_name in STRATEGIES:
        print(f"\n--- Strategy: {strategy_name} ---")
        try:
            result = run_strategy_pipeline(
                strategy_name, session_label, prices, fx_rates, signals, all_prices_real
            )
            strategy_results[strategy_name] = result
            print(
                f"  [{strategy_name}] Total: {result['total_value_eur']:.2f} EUR | "
                f"Trades: {len(result['transactions'])}"
            )
        except Exception as e:
            print(f"[ERROR] Strategy {strategy_name} failed: {e}")
            strategy_results[strategy_name] = None

    # --- Backward compat: also update legacy portfolio_history.json ---
    try:
        legacy_portfolio = load_portfolio()
        legacy_result = strategy_results.get("equal_weight")
        if legacy_result:
            eq_portfolio = legacy_result["portfolio"]
            legacy_portfolio["current_positions"] = eq_portfolio["current_positions"]
            legacy_portfolio["metadata"]["current_cash"] = eq_portfolio["metadata"]["current_cash"]
            legacy_portfolio["metadata"]["price_source"] = eq_portfolio["metadata"].get(
                "price_source", "yfinance"
            )
            log_iteration(
                legacy_portfolio,
                session_label,
                legacy_result["total_value_eur"],
                legacy_result["transactions"],
                prices,
                "\n".join(legacy_result["reasoning_parts"]),
            )
    except Exception as e:
        print(f"[WARN] Legacy portfolio update failed: {e}")

    # --- Determine primary result for Telegram (equal_weight) ---
    primary = strategy_results.get("equal_weight") or next(
        (v for v in strategy_results.values() if v), None
    )
    if not primary:
        print("[ERROR] All strategies failed.")
        return 0.0

    total_value_eur = primary["total_value_eur"]
    cash_eur = primary["cash_eur"]
    has_any_trades = any(
        r and r["has_trades"] for r in strategy_results.values()
    )

    # --- Print summary ---
    print("\n=== STRATEGY SUMMARY ===")
    for sname, result in strategy_results.items():
        if result:
            initial = result["portfolio"]["metadata"].get("initial_capital", INITIAL_CAPITAL)
            ret_pct = (result["total_value_eur"] - initial) / initial * 100 if initial > 0 else 0
            print(f"  {sname:20s}: {result['total_value_eur']:.2f} EUR ({ret_pct:+.2f}%)")

    # --- Telegram report ---
    report = build_telegram_report(
        session_label,
        strategy_results,
        primary["portfolio"],
        prices,
    )
    send_telegram_message(report, session=session_label, has_trades=has_any_trades)

    # --- Chart (equal_weight primary) ---
    try:
        chart_path = generate_dashboard(primary["portfolio"], UNIVERSE, total_value_eur)
        pos_summary = " | ".join(
            "{}:{}x".format(t, p["shares"])
            for t, p in sorted(primary["portfolio"]["current_positions"].items())
        )
        photo_caption = (
            "{} - Portfolio (EW): {:.2f}EUR - {} posizioni\n{}\nCash: {:.2f}EUR".format(
                session_label.upper(),
                total_value_eur,
                len(primary["portfolio"]["current_positions"]),
                pos_summary[:400],
                cash_eur,
            )
        )
        send_telegram_photo(
            photo_caption, chart_path, session=session_label, has_trades=has_any_trades
        )
    except Exception as e:
        print(f"[WARN] Chart generation/send failed: {e}")

    # --- Dashboard HTML (multi-portfolio) ---
    try:
        all_portfolios = {
            sname: result["portfolio"]
            for sname, result in strategy_results.items()
            if result
        }
        html = build_html(all_portfolios, signals)
        docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
        os.makedirs(docs_dir, exist_ok=True)
        html_path = os.path.join(docs_dir, "index.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[OK] Dashboard HTML saved: {html_path}")
    except Exception as e:
        print(f"[WARN] Dashboard HTML generation failed: {e}")

    print(f"\n[DONE] Session {session_label} completed. Primary total: {total_value_eur:.2f} EUR")
    return total_value_eur


# ---------------------------------------------------------------------------
# Telegram report (multi-strategy)
# ---------------------------------------------------------------------------

def build_telegram_report(
    session: str,
    strategy_results: dict,
    primary_portfolio: dict,
    prices: dict,
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sep = "-" * 25
    lines = [
        "AI HEDGE FUND — {}".format(session.upper()),
        sep,
    ]

    # Strategy comparison
    lines.append("CONFRONTO STRATEGIE:")
    for sname in STRATEGIES:
        result = strategy_results.get(sname)
        if result:
            initial = result["portfolio"]["metadata"].get("initial_capital", INITIAL_CAPITAL)
            total = result["total_value_eur"]
            ret_pct = (total - initial) / initial * 100 if initial > 0 else 0
            arrow = "+" if ret_pct >= 0 else ""
            lines.append(f"  {sname:20s}: {total:.2f}EUR ({arrow}{ret_pct:.2f}%)")
        else:
            lines.append(f"  {sname:20s}: ERROR")
    lines.append("")

    # Equal-weight detail: transactions + top positions P&L
    ew_result = strategy_results.get("equal_weight")
    if ew_result:
        lines.append(sep)
        if ew_result["transactions"]:
            lines.append("TRANSAZIONI (equal_weight):")
            for t in ew_result["transactions"]:
                if t["action"] == "BUY":
                    lines.append(
                        "  BUY {}x {} @ {:.2f}€ = {:.2f}€".format(
                            t["shares"], t["ticker"], t["price_eur"], t["total_cost_eur"]
                        )
                    )
                else:
                    lines.append(
                        "  SELL {}x {} @ {:.2f}€ = +{:.2f}€".format(
                            t["shares"], t["ticker"], t["price_eur"], t["total_proceeds_eur"]
                        )
                    )
        else:
            lines.append("Nessuna transazione oggi.")

        # Show P&L for open positions (only at "sera")
        if session == "sera":
            pos = ew_result["portfolio"].get("current_positions", {})
            if pos:
                lines.append("")
                lines.append("POSIZIONI P&L (equal_weight):")
                for ticker in sorted(pos.keys()):
                    entry = pos[ticker]
                    cur_price = prices.get(ticker, entry["avg_price"])
                    currency = UNIVERSE.get(ticker, {}).get("currency", "EUR")
                    fx = 0.92 if currency == "USD" else (1.17 if currency == "GBP" else 1.0)
                    cur_eur = cur_price * fx
                    equity = entry["shares"] * cur_eur
                    cost = entry["shares"] * entry["avg_price"]
                    pnl_e = equity - cost
                    pnl_p = (pnl_e / cost * 100) if cost > 0 else 0
                    sign = "+" if pnl_e >= 0 else ""
                    lines.append(
                        "  {}: {}x | {:.2f}€ | P&L {}{:.2f}€ ({}{:.1f}%)".format(
                            ticker, entry["shares"], cur_eur, sign, pnl_e, sign, pnl_p
                        )
                    )
        lines.append("")

    lines.append("Aggiornato: {}".format(timestamp))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Hedge Fund Multi-Strategy Pipeline")
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
