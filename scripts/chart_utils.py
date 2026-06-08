import os
from datetime import datetime, timezone
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

CHART_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "report_chart.png")


def _load_history(portfolio: dict) -> list[dict]:
    return portfolio.get("iterations_log", [])


def _plot_equity_curve(ax: plt.Axes, history: list[dict]) -> None:
    if not history:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        return
    timestamps = []
    values = []
    cash = []
    for entry in history:
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
        except (ValueError, TypeError):
            continue
        timestamps.append(ts)
        values.append(entry.get("total_value_eur", 0))
        cash.append(entry.get("current_cash", 0))

    ax.plot(timestamps, values, label="Portfolio", color="#2563eb", linewidth=2)
    ax.plot(
        timestamps, cash, label="Cash", color="#16a34a", linewidth=1.5, linestyle="--"
    )
    ax.fill_between(timestamps, cash, values, alpha=0.1, color="#2563eb")
    ax.set_title("Equity Curve", fontweight="bold", fontsize=11)
    ax.set_ylabel("EUR")
    ax.legend(loc="upper left", fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
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


def _plot_deviation(
    ax: plt.Axes, portfolio: dict, tickers: dict, total_eur: float
) -> None:
    total = total_eur
    target_per_ticker = total / len(tickers) if tickers else 0

    history = portfolio.get("iterations_log", [])
    last_prices = history[-1].get("prices_used", {}) if history else {}

    positions = portfolio.get("current_positions", {})
    ticker_list = sorted(tickers.keys())

    deviations = []
    labels = []
    colors = []
    for t in ticker_list:
        price = last_prices.get(t, 100.0)
        shares = positions.get(t, {}).get("shares", 0)
        current_val = price * shares
        dev = ((current_val - target_per_ticker) / total * 100) if total > 0 else 0
        deviations.append(dev)
        labels.append(t)
        colors.append("#dc2626" if dev > 0 else "#16a34a")

    bars = ax.barh(labels, deviations, color=colors, height=0.6)
    ax.axvline(0, color="gray", linewidth=0.5)
    ax.set_title("Deviation from target (%)", fontweight="bold", fontsize=11)
    ax.set_xlabel("%")
    for bar, dev in zip(bars, deviations):
        if abs(dev) > 1:
            ax.text(
                dev + (1 if dev >= 0 else -1),
                bar.get_y() + bar.get_height() / 2,
                f"{dev:+.1f}%",
                va="center",
                fontsize=6,
            )
    ax.grid(True, axis="x", alpha=0.3)


def generate_dashboard(
    portfolio: dict,
    tickers: dict[str, dict],
    total_value_eur: float,
) -> str:
    history = _load_history(portfolio)

    fig = plt.figure(figsize=(12, 8))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.1, 1], hspace=0.3, wspace=0.25)

    ax1 = fig.add_subplot(gs[0, :])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[1, 1])

    _plot_equity_curve(ax1, history)
    _plot_allocation(ax2, portfolio, tickers)
    _plot_deviation(ax3, portfolio, tickers, total_value_eur)

    fig.suptitle(
        f"Paper Trading Dashboard — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        fontsize=13,
        fontweight="bold",
        y=0.98,
    )

    os.makedirs(os.path.dirname(CHART_PATH), exist_ok=True)
    fig.savefig(CHART_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Chart saved: {CHART_PATH}")
    return CHART_PATH
