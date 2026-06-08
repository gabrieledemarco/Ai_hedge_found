import json
import os
from datetime import datetime, timezone
from typing import Any

PORTFOLIO_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "portfolio_history.json"
)


def load_portfolio() -> dict[str, Any]:
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def save_portfolio(portfolio: dict[str, Any]) -> None:
    with open(PORTFOLIO_PATH, "w") as f:
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
