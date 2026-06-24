import os
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

CHART_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "report_chart.png")

_INITIAL_CAPITAL = 3000.0
_STRATEGY_COLORS = {
    "equal_weight": "#2563eb",
    "momentum":     "#f59e0b",
    "fundamental":  "#16a34a",
    "sentiment":    "#dc2626",
}
_STRATEGY_LABELS = {
    "equal_weight": "Equal Weight",
    "momentum":     "Momentum",
    "fundamental":  "Fundamental",
    "sentiment":    "Sentiment",
}


def _plot_equity_overlay(ax: plt.Axes, portfolios: dict[str, dict]) -> None:
    """Plot equity curves for all strategies on the same axis."""
    has_data = False
    for sname, portfolio in portfolios.items():
        history = portfolio.get("iterations_log", [])
        timestamps, values = [], []
        for entry in history:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
            except (ValueError, TypeError):
                continue
            timestamps.append(ts)
            values.append(entry.get("total_value_eur", 0))
        if timestamps:
            ax.plot(
                timestamps, values,
                label=_STRATEGY_LABELS.get(sname, sname),
                color=_STRATEGY_COLORS.get(sname, "#888"),
                linewidth=2,
            )
            has_data = True

    if not has_data:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center",
                transform=ax.transAxes, fontsize=12, color="gray")

    ax.axhline(_INITIAL_CAPITAL, color="gray", linewidth=0.8,
               linestyle=":", alpha=0.6, label="Capital iniziale")
    ax.set_title("Equity Curve — Tutte le strategie", fontweight="bold", fontsize=11)
    ax.set_ylabel("EUR")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=20, ha="right", fontsize=7)
    ax.grid(True, alpha=0.3)


def _plot_allocation(ax: plt.Axes, portfolio: dict, tickers: list[dict]) -> None:
    positions = portfolio.get("current_positions", {})
    if not positions:
        ax.text(
            0.5, 0.5, "No positions", ha="center", va="center", transform=ax.transAxes
        )
        return

    labels = []
    sizes = []
    for ticker, info in tickers.items():
        shares = positions.get(ticker, {}).get("shares", 0)
        if shares > 0:
            labels.append(ticker)
            sizes.append(shares)

    if not sizes:
        ax.text(
            0.5, 0.5, "No positions", ha="center", va="center", transform=ax.transAxes
        )
        return

    colors = plt.cm.Set3(range(len(labels)))
    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=None,
        autopct="%1.0f%%",
        startangle=90,
        colors=colors,
        pctdistance=0.75,
    )
    for t in autotexts:
        t.set_fontsize(7)
    ax.set_title("Allocation (shares)", fontweight="bold", fontsize=11)

    sector_groups: dict[str, int] = {}
    for ticker, info in tickers.items():
        shares = positions.get(ticker, {}).get("shares", 0)
        if shares > 0:
            sector = info.get("sector", "Other")
            sector_groups[sector] = sector_groups.get(sector, 0) + shares
    legend_labels = [
        f"{t}"
        for t, info in tickers.items()
        if positions.get(t, {}).get("shares", 0) > 0
    ]
    if legend_labels:
        ax.legend(
            wedges,
            legend_labels,
            loc="lower center",
            fontsize=6,
            ncol=min(3, len(legend_labels)),
            bbox_to_anchor=(0.5, -0.25),
        )


def _plot_pnl_bars(
    ax: plt.Axes, portfolio: dict, tickers: dict, prices: dict
) -> None:
    """Horizontal bar chart of unrealized P&L (EUR) per position."""
    positions = portfolio.get("current_positions", {})
    if not positions:
        ax.text(0.5, 0.5, "No positions", ha="center", va="center",
                transform=ax.transAxes)
        return

    labels, pnls = [], []
    for ticker in sorted(positions.keys()):
        entry = positions[ticker]
        cur_price = prices.get(ticker, entry["avg_price"])
        currency = tickers.get(ticker, {}).get("currency", "EUR")
        fx = 0.92 if currency == "USD" else (1.17 if currency == "GBP" else 1.0)
        cur_eur = cur_price * fx
        pnl = entry["shares"] * (cur_eur - entry["avg_price"])
        labels.append(ticker)
        pnls.append(pnl)

    colors = ["#16a34a" if p >= 0 else "#dc2626" for p in pnls]
    bars = ax.barh(labels, pnls, color=colors, height=0.6, alpha=0.85)
    ax.axvline(0, color="gray", linewidth=0.7)
    ax.set_title("Unrealized P&L per posizione (€)", fontweight="bold", fontsize=11)
    ax.set_xlabel("EUR")
    for bar, pnl in zip(bars, pnls):
        if abs(pnl) >= 0.5:
            x = pnl + (0.3 if pnl >= 0 else -0.3)
            ax.text(x, bar.get_y() + bar.get_height() / 2,
                    f"{pnl:+.1f}€", va="center", fontsize=6)
    ax.grid(True, axis="x", alpha=0.3)
    ax.tick_params(axis="y", labelsize=7)


def generate_dashboard(
    portfolios: dict[str, dict],
    primary_portfolio: dict,
    tickers: dict[str, dict],
    prices: dict[str, float],
    total_value_eur: float,
) -> str:
    """Generate the dashboard chart with equity overlay + allocation + P&L bars."""
    fig = plt.figure(figsize=(13, 9))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.2, 1], hspace=0.35, wspace=0.28)

    ax1 = fig.add_subplot(gs[0, :])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[1, 1])

    _plot_equity_overlay(ax1, portfolios)
    _plot_allocation(ax2, primary_portfolio, tickers)
    _plot_pnl_bars(ax3, primary_portfolio, tickers, prices)

    fig.suptitle(
        f"Paper Trading Dashboard — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        fontsize=13,
        fontweight="bold",
        y=0.99,
    )

    os.makedirs(os.path.dirname(CHART_PATH), exist_ok=True)
    fig.savefig(CHART_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Chart saved: {CHART_PATH}")
    return CHART_PATH
