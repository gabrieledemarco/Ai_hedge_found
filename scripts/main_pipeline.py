import argparse
import os
import sys
import math
import json
from datetime import datetime, timezone

import requests

# Ensure scripts/ directory is on the path so config and strategies are importable
sys.path.insert(0, os.path.dirname(__file__))

from config import UNIVERSE, STRATEGIES, INITIAL_CAPITAL, REBALANCE_THRESHOLD
from fetch_prices import get_prices
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
# FX helpers
# ---------------------------------------------------------------------------


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


def convert_to_eur(amount: float, currency: str, fx_rates: dict | None = None) -> float:
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
        print(
            "[WARN] Imposta i GitHub Secrets: Settings → Secrets and variables → Actions"
        )
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
    failed_tickers: set,
) -> dict:
    """
    Run the trading pipeline for one strategy.
    Returns {total_value_eur, cash_eur, transactions, reasoning_parts, portfolio}.

    failed_tickers: set of tickers whose price fetch failed (using fallback values).
    Trading is skipped only for those specific tickers; all others trade normally.
    All trading is suspended only when ALL tickers failed.
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
        pos = portfolio["current_positions"].get(ticker, {})
        shares = pos.get("shares", 0)
        # For tickers with fallback price, use avg_price (cost basis in EUR) to avoid
        # inflation from a generic 100 EUR fallback on cheap stocks in large lots.
        if ticker in failed_tickers:
            pos_val_eur = pos.get("avg_price", price_eur) * shares
        else:
            pos_val_eur = price_eur * shares
        position_values_eur[ticker] = pos_val_eur
        portfolio_value_eur += pos_val_eur

    cash_eur = portfolio["metadata"]["current_cash"]
    portfolio_value_eur += cash_eur

    all_failed = len(failed_tickers) >= len(tickers)
    if all_failed:
        msg = (
            "ATTENZIONE: tutti i prezzi sono fallback. "
            "Trading disabilitato, solo report."
        )
        portfolio["metadata"]["price_source"] = "fallback"
        log_iteration_for_strategy(
            strategy_name,
            portfolio,
            session_label,
            portfolio_value_eur,
            [],
            prices,
            msg,
        )
        return {
            "total_value_eur": portfolio_value_eur,
            "cash_eur": cash_eur,
            "transactions": [],
            "reasoning_parts": [msg],
            "portfolio": portfolio,
            "has_trades": False,
        }

    n_real = len(tickers) - len(failed_tickers)
    portfolio["metadata"]["price_source"] = f"investing.com({n_real}/{len(tickers)})"

    # --- Compute target weights from strategy ---
    weights = strategy.compute_weights(UNIVERSE, prices, signals)

    transactions = []
    reasoning_parts = []
    has_trades = False

    if failed_tickers:
        reasoning_parts.append(
            f"ATTENZIONE: prezzi non disponibili per {sorted(failed_tickers)}. "
            "Trading sospeso per questi titoli."
        )

    for ticker in tickers:
        # Skip trading for tickers whose price fetch failed
        if ticker in failed_tickers:
            reasoning_parts.append(f"{ticker}: SKIP (prezzo non disponibile)")
            continue
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
        strategy_name,
        portfolio,
        session_label,
        total_value_eur,
        transactions,
        prices,
        reasoning,
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

    # Fetch prices: investing.com (investiny) → yfinance bulk fallback
    prices, failed_tickers = get_prices(tickers, UNIVERSE)

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
                strategy_name, session_label, prices, fx_rates, signals, failed_tickers
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
            legacy_portfolio["metadata"]["current_cash"] = eq_portfolio["metadata"][
                "current_cash"
            ]
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
    has_any_trades = any(r and r["has_trades"] for r in strategy_results.values())

    # --- Print summary ---
    print("\n=== STRATEGY SUMMARY ===")
    for sname, result in strategy_results.items():
        if result:
            initial = result["portfolio"]["metadata"].get(
                "initial_capital", INITIAL_CAPITAL
            )
            ret_pct = (
                (result["total_value_eur"] - initial) / initial * 100
                if initial > 0
                else 0
            )
            print(
                f"  {sname:20s}: {result['total_value_eur']:.2f} EUR ({ret_pct:+.2f}%)"
            )

    # --- Telegram report ---
    report = build_telegram_report(
        session_label,
        strategy_results,
        primary["portfolio"],
        prices,
        failed_tickers=failed_tickers,
    )
    send_telegram_message(report, session=session_label, has_trades=has_any_trades)

    # --- Chart (equity overlay all strategies + P&L bars for primary) ---
    try:
        all_portfolios = {
            sname: result["portfolio"]
            for sname, result in strategy_results.items()
            if result
        }
        chart_path = generate_dashboard(
            all_portfolios, primary["portfolio"], UNIVERSE, prices, total_value_eur
        )
        ret_pct = (total_value_eur - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        arrow = "+" if ret_pct >= 0 else ""
        strategy_line = " | ".join(
            "{}: {:.0f}€".format(s, r["total_value_eur"])
            for s, r in strategy_results.items()
            if r
        )
        photo_caption = (
            "{} | EW: {:.0f}€ ({}{:.1f}%)\n{}\nCash: {:.0f}€".format(
                session_label.upper(),
                total_value_eur,
                arrow,
                ret_pct,
                strategy_line,
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

    print(
        f"\n[DONE] Session {session_label} completed. Primary total: {total_value_eur:.2f} EUR"
    )
    return total_value_eur


# ---------------------------------------------------------------------------
# Telegram report (multi-strategy)
# ---------------------------------------------------------------------------


def _position_pnl_line(ticker: str, entry: dict, prices: dict) -> str:
    """Format a position with buy price, current price and unrealized P&L."""
    cur_price = prices.get(ticker, entry["avg_price"])
    currency = UNIVERSE.get(ticker, {}).get("currency", "EUR")
    fx = 0.92 if currency == "USD" else (1.17 if currency == "GBP" else 1.0)
    cur_eur = cur_price * fx
    avg_eur = entry["avg_price"]
    shares = entry["shares"]
    pnl_eur = shares * (cur_eur - avg_eur)
    pnl_pct = (pnl_eur / (shares * avg_eur) * 100) if avg_eur > 0 else 0
    sign = "+" if pnl_eur >= 0 else ""
    return "  {}: {}x | {:.0f}€→{:.0f}€ | {}{:.1f}% ({}{:.0f}€)".format(
        ticker, shares, avg_eur, cur_eur, sign, pnl_pct, sign, pnl_eur
    )


def _last_known_prices(strategy_results: dict) -> dict[str, float]:
    """Extract last known real prices from iterations_log to use as fallback display."""
    last = {}
    for result in strategy_results.values():
        if not result:
            continue
        logs = result["portfolio"].get("iterations_log", [])
        for entry in reversed(logs):
            pu = entry.get("prices_used", {})
            for t, p in pu.items():
                if t not in last and p not in (100.0, 150.0):
                    last[t] = p
    return last


def build_telegram_report(
    session: str,
    strategy_results: dict,
    primary_portfolio: dict,
    prices: dict,
    failed_tickers: set = None,
) -> str:
    TELEGRAM_LIMIT = 4000
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sep = "-" * 25
    if failed_tickers is None:
        failed_tickers = set()
    all_failed = len(failed_tickers) >= len(prices)

    lines = ["AI HEDGE FUND — {}".format(session.upper()), sep]

    if all_failed:
        lines.append("⚠️  PREZZI NON DISPONIBILI (fallback totale)")
        lines.append("     Trading sospeso. Valori calcolati con ultimo prezzo noto.")
        lines.append("")
    elif failed_tickers:
        failed_list = ", ".join(sorted(failed_tickers))
        lines.append(f"⚠️  Prezzi non disponibili per: {failed_list}")
        lines.append("     Trading sospeso per questi titoli.")
        lines.append("")

    # Performance summary — all 4 strategies
    _SHORT_LABEL = {
        "equal_weight": "EqW",
        "momentum":     "Mom",
        "fundamental":  "Fun",
        "sentiment":    "Sen",
    }
    lines.append("📈 CONFRONTO STRATEGIE")
    totals = {}
    for sname in STRATEGIES:
        result = strategy_results.get(sname)
        short = _SHORT_LABEL.get(sname, sname[:3].upper())
        if result:
            initial = result["portfolio"]["metadata"].get(
                "initial_capital", INITIAL_CAPITAL
            )
            total = result["total_value_eur"]
            totals[sname] = total
            ret_pct = (total - initial) / initial * 100 if initial > 0 else 0
            n_pos = len(result["portfolio"].get("current_positions", {}))
            cash = result["portfolio"]["metadata"].get("current_cash", 0)
            arrow = "+" if ret_pct >= 0 else ""
            lines.append(
                "  {} {:.0f}€ ({}{:.1f}%) {}pos {:.0f}€cash".format(
                    short, total, arrow, ret_pct, n_pos, cash
                )
            )
        else:
            lines.append(f"  {short} ERROR")

    # Warn if strategies have identical values (signals not yet available)
    unique_totals = set(round(v, 0) for v in totals.values())
    if len(unique_totals) < len(totals):
        lines.append("")
        lines.append("ℹ️  Alcune strategie hanno valori identici: signals.json")
        lines.append("   non ancora popolato. Esegui market_analysis workflow.")
    lines.append("")

    # Transactions — all strategies that had trades today
    any_trades = False
    trade_lines = []
    for sname in STRATEGIES:
        result = strategy_results.get(sname)
        if result and result["transactions"]:
            any_trades = True
            trade_lines.append("TRADES {}:".format(sname.upper()))
            for t in result["transactions"]:
                if t["action"] == "BUY":
                    trade_lines.append(
                        "  BUY {}x {} @ {:.0f}€".format(
                            t["shares"], t["ticker"], t["price_eur"]
                        )
                    )
                else:
                    trade_lines.append(
                        "  SELL {}x {} @ {:.0f}€".format(
                            t["shares"], t["ticker"], t["price_eur"]
                        )
                    )

    if any_trades:
        lines.extend(trade_lines)
    else:
        lines.append("Nessuna transazione oggi.")
    lines.append("")

    # Positions with buy price, current price and unrealized P&L — all sessions
    _STRATEGY_LABEL = {
        "equal_weight": "Equal Weight",
        "momentum":     "Momentum",
        "fundamental":  "Fundamental",
        "sentiment":    "Sentiment",
    }

    lines.append(sep)
    lines.append("📊 PORTAFOGLI (buy€ → cur€ | P&L)")

    # For failed tickers use last known real price
    if failed_tickers:
        last_known = _last_known_prices(strategy_results)
        display_prices = dict(prices)
        for t in failed_tickers:
            if t in last_known:
                display_prices[t] = last_known[t]
    else:
        display_prices = prices

    for sname in STRATEGIES:
        result = strategy_results.get(sname)
        if not result:
            continue
        pos = result["portfolio"].get("current_positions", {})
        initial = result["portfolio"]["metadata"].get("initial_capital", INITIAL_CAPITAL)
        total = result.get("total_value_eur", initial)
        ret_pct = (total - initial) / initial * 100 if initial > 0 else 0
        arrow = "+" if ret_pct >= 0 else ""
        cash = result["portfolio"]["metadata"].get("current_cash", 0)
        label = _STRATEGY_LABEL.get(sname, sname.replace("_", " ").title())
        lines.append("")
        lines.append("▪ {} — {:.0f}€ ({}{:.1f}%) | cash {:.0f}€".format(
            label, total, arrow, ret_pct, cash
        ))
        if not pos:
            lines.append("  solo cash")
        else:
            for ticker in sorted(pos.keys()):
                lines.append(_position_pnl_line(ticker, pos[ticker], display_prices))
    lines.append("")

    lines.append("Aggiornato: {}".format(timestamp))

    text = "\n".join(lines)
    if len(text) > TELEGRAM_LIMIT:
        text = text[: TELEGRAM_LIMIT - 20] + "\n...[troncato]"
    return text


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AI Hedge Fund Multi-Strategy Pipeline"
    )
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
