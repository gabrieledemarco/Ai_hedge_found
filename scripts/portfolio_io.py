import json
import os
from datetime import datetime, timezone
from typing import Any

PORTFOLIO_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "portfolio_history.json"
)

PORTFOLIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "portfolios")


def load_portfolio() -> dict[str, Any]:
    """Load legacy single portfolio (backward compat)."""
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def save_portfolio(portfolio: dict[str, Any]) -> None:
    """Save legacy single portfolio (backward compat)."""
    with open(PORTFOLIO_PATH, "w") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _strategy_path(strategy_name: str) -> str:
    return os.path.join(PORTFOLIOS_DIR, f"{strategy_name}.json")


def load_portfolio_for_strategy(strategy_name: str) -> dict[str, Any]:
    """Load portfolio for a specific strategy, initializing if not present."""
    path = _strategy_path(strategy_name)
    os.makedirs(PORTFOLIOS_DIR, exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    # Initialize fresh portfolio
    return {
        "strategy": strategy_name,
        "metadata": {
            "initial_capital": 3000.0,
            "current_cash": 3000.0,
            "price_source": "yfinance",
        },
        "current_positions": {},
        "iterations_log": [],
    }


def save_portfolio_for_strategy(strategy_name: str, portfolio: dict[str, Any]) -> None:
    """Save portfolio for a specific strategy."""
    path = _strategy_path(strategy_name)
    os.makedirs(PORTFOLIOS_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)
        f.write("\n")


def log_iteration(
    portfolio: dict[str, Any],
    session: str,
    total_value_eur: float,
    transactions: list[dict[str, Any]],
    prices: dict[str, float],
    reasoning: str,
) -> None:
    """Log iteration for legacy single portfolio (backward compat)."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session": session,
        "total_value_eur": round(total_value_eur, 2),
        "current_cash": round(portfolio["metadata"]["current_cash"], 2),
        "positions": {
            ticker: {
                "shares": int(pos["shares"]),
                "avg_price": round(pos["avg_price"], 4),
            }
            for ticker, pos in portfolio["current_positions"].items()
        },
        "prices_used": {k: round(v, 4) for k, v in prices.items()},
        "transactions": transactions,
        "reasoning": reasoning,
    }
    portfolio["iterations_log"].append(entry)
    save_portfolio(portfolio)


def log_iteration_for_strategy(
    strategy_name: str,
    portfolio: dict[str, Any],
    session: str,
    total_value_eur: float,
    transactions: list[dict[str, Any]],
    prices: dict[str, float],
    reasoning: str,
) -> None:
    """Log iteration for a specific strategy portfolio."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session": session,
        "total_value_eur": round(total_value_eur, 2),
        "current_cash": round(portfolio["metadata"]["current_cash"], 2),
        "positions": {
            ticker: {
                "shares": int(pos["shares"]),
                "avg_price": round(pos["avg_price"], 4),
            }
            for ticker, pos in portfolio["current_positions"].items()
        },
        "prices_used": {k: round(v, 4) for k, v in prices.items()},
        "transactions": transactions,
        "reasoning": reasoning,
    }
    portfolio["iterations_log"].append(entry)
    save_portfolio_for_strategy(strategy_name, portfolio)
