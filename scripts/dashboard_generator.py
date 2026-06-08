import os
import json
import math
import base64
import io
from datetime import datetime, timezone
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

UNIVERSE: dict[str, dict] = {}

DASHBOARD_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "index.html")


def _load_universe():
    global UNIVERSE
    if not UNIVERSE:
        from main_pipeline import UNIVERSE as U

        UNIVERSE = U


def _calc_daily_returns(values: list[float]) -> list[float]:
    if len(values) < 2:
        return []
    return [
        (values[i] - values[i - 1]) / values[i - 1] * 100 for i in range(1, len(values))
    ]


def _calc_max_drawdown(values: list[float]) -> float:
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _compute_metrics(history: list[dict]) -> dict[str, Any]:
    if not history:
        return {}
    values = [e["total_value_eur"] for e in history]
    initial = history[0].get("total_value_eur", values[0])
    final = values[-1]
    total_return = (final - initial) / initial * 100
    n = len(values)
    daily_rets = _calc_daily_returns(values)
    n_days = len(daily_rets)
    avg_daily_ret = sum(daily_rets) / n_days if n_days > 0 else 0
    daily_vol = (
        math.sqrt(sum((r - avg_daily_ret) ** 2 for r in daily_rets) / n_days)
        if n_days > 0
        else 0
    )
    trading_days_year = 252
    ann_return = total_return / n * trading_days_year if n > 0 else 0
    ann_vol = daily_vol * math.sqrt(trading_days_year)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0
    max_dd = _calc_max_drawdown(values)
    calmar = ann_return / max_dd if max_dd > 0 else 0
    gains = [r for r in daily_rets if r > 0]
    losses = [r for r in daily_rets if r < 0]
    win_rate = len(gains) / n_days * 100 if n_days > 0 else 0
    avg_win = sum(gains) / len(gains) if gains else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    profit_factor = (
        abs(sum(gains) / sum(losses)) if losses and sum(losses) != 0 else float("inf")
    )
    return {
        "total_return": total_return,
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "n_entries": n,
        "initial": initial,
        "final": final,
        "daily_rets": daily_rets,
        "values": values,
    }


def _fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#0f172a")
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return f"data:image/png;base64,{data}"


def generate_charts_html(portfolio: dict) -> str:
    _load_universe()
    history = portfolio.get("iterations_log", [])
    positions = portfolio.get("current_positions", {})
    metrics = _compute_metrics(history)
    cash = portfolio["metadata"].get("current_cash", 0)
    total_eur = metrics.get("final", cash)
    values = metrics.get("values", [])
    daily_rets = metrics.get("daily_rets", [])
    timestamps = [e["timestamp"] for e in history] if history else []

    charts_html = ""

    # --- Chart 1: Equity Curve ---
    fig, ax = plt.subplots(figsize=(10, 3.2))
    if timestamps:
        ts = [datetime.fromisoformat(t) for t in timestamps]
        ax.plot(ts, values, color="#22c55e", linewidth=2, label="Portfolio")
        ax.fill_between(ts, values, alpha=0.1, color="#22c55e")
        cash_hist = [e["current_cash"] for e in history]
        ax.plot(
            ts, cash_hist, color="#3b82f6", linewidth=1.2, linestyle="--", label="Cash"
        )
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.legend(fontsize=8)
    ax.set_title("Equity Curve", color="#f8fafc", fontweight="bold")
    ax.set_facecolor("#1e293b")
    fig.patch.set_facecolor("#0f172a")
    ax.tick_params(colors="#94a3b8")
    ax.spines["bottom"].set_color("#334155")
    ax.spines["left"].set_color("#334155")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, alpha=0.15, color="#334155")
    ax.set_ylabel("EUR", color="#94a3b8")
    charts_html += f'<img src="{_fig_to_b64(fig)}" style="width:100%;border-radius:8px;" alt="Equity Curve">'

    # --- Chart 2: Allocation + Sector side-by-side ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.2))

    if positions:
        labels = []
        sizes = []
        for t in sorted(positions.keys()):
            labels.append(t)
            sizes.append(positions[t]["shares"])
        colors_al = plt.cm.Set3(range(len(labels)))
        wedges, texts, autotexts = ax1.pie(
            sizes,
            labels=None,
            autopct="%1.0f%%",
            startangle=90,
            colors=colors_al,
            pctdistance=0.7,
        )
        for t in autotexts:
            t.set_fontsize(7)
        ax1.legend(
            wedges,
            labels,
            loc="lower center",
            fontsize=6,
            ncol=min(3, len(labels)),
            bbox_to_anchor=(0.5, -0.25),
        )
    ax1.set_title(
        "Allocation (shares)", color="#f8fafc", fontweight="bold", fontsize=10
    )

    sector_values: dict[str, float] = {}
    pos_equity: dict[str, float] = {}
    if positions and timestamps:
        last_prices = history[-1].get("prices_used", {})
        for t, p in positions.items():
            info = UNIVERSE.get(t, {})
            cur = last_prices.get(t, p["avg_price"])
            ccy = info.get("currency", "EUR")
            if ccy == "USD":
                cur *= 0.8663
            elif ccy == "GBP":
                cur *= 1.17
            eq_val = p["shares"] * cur
            pos_equity[t] = eq_val
            sector = info.get("sector", "Other")
            sector_values[sector] = sector_values.get(sector, 0) + eq_val

    if sector_values:
        sec_labels = list(sector_values.keys())
        sec_sizes = list(sector_values.values())
        colors_sec = plt.cm.Set2(range(len(sec_labels)))
        ax2.barh(sec_labels, sec_sizes, color=colors_sec, height=0.6)
        for i, v in enumerate(sec_sizes):
            ax2.text(v + 5, i, f"{v:.0f}€", va="center", fontsize=8, color="#94a3b8")
    ax2.set_title(
        "Sector Exposure (EUR)", color="#f8fafc", fontweight="bold", fontsize=10
    )
    ax2.set_facecolor("#1e293b")
    ax2.tick_params(colors="#94a3b8")
    ax2.spines["bottom"].set_color("#334155")
    ax2.spines["left"].set_color("#334155")
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.grid(True, alpha=0.15, axis="x", color="#334155")

    fig.patch.set_facecolor("#0f172a")
    charts_html += f'<img src="{_fig_to_b64(fig)}" style="width:100%;border-radius:8px;margin-top:12px;" alt="Allocation and Sector">'

    # --- Chart 3: Drawdown + PnL side-by-side ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.2))

    if values:
        dd_values = []
        peak = values[0]
        for v in values:
            if v > peak:
                peak = v
            dd_values.append((v - peak) / peak * 100)
        ts = [datetime.fromisoformat(t) for t in timestamps]
        ax1.fill_between(ts, dd_values, 0, color="#ef4444", alpha=0.7)
        ax1.plot(ts, dd_values, color="#ef4444", linewidth=1)
        ax1.axhline(0, color="#94a3b8", linewidth=0.5)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax1.set_title("Drawdown", color="#f8fafc", fontweight="bold", fontsize=10)
    ax1.set_facecolor("#1e293b")
    ax1.tick_params(colors="#94a3b8")
    ax1.spines["bottom"].set_color("#334155")
    ax1.spines["left"].set_color("#334155")
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.grid(True, alpha=0.15, color="#334155")
    ax1.set_ylabel("%", color="#94a3b8")

    pnl_tickers = []
    pnl_values = []
    pnl_colors = []
    for t in sorted(pos_equity.keys()):
        p = positions[t]
        eq = pos_equity[t]
        cost = p["shares"] * p["avg_price"]
        pnl = eq - cost
        pnl_tickers.append(t)
        pnl_values.append(pnl)
        pnl_colors.append("#22c55e" if pnl >= 0 else "#ef4444")

    if pnl_tickers:
        bars = ax2.barh(pnl_tickers, pnl_values, color=pnl_colors, height=0.6)
        for bar, val in zip(bars, pnl_values):
            if abs(val) > 1:
                ax2.text(
                    val + (2 if val >= 0 else -2),
                    bar.get_y() + bar.get_height() / 2,
                    f"{val:+.1f}€",
                    va="center",
                    fontsize=7,
                    color="#94a3b8",
                )
    ax2.set_title("PnL by Asset", color="#f8fafc", fontweight="bold", fontsize=10)
    ax2.set_facecolor("#1e293b")
    ax2.tick_params(colors="#94a3b8")
    ax2.spines["bottom"].set_color("#334155")
    ax2.spines["left"].set_color("#334155")
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.axvline(0, color="#94a3b8", linewidth=0.5)
    ax2.grid(True, alpha=0.15, axis="x", color="#334155")

    fig.patch.set_facecolor("#0f172a")
    charts_html += f'<img src="{_fig_to_b64(fig)}" style="width:100%;border-radius:8px;margin-top:12px;" alt="Drawdown and PnL">'

    # --- Chart 4: Daily Returns Histogram ---
    if daily_rets:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.hist(
            daily_rets,
            bins=max(10, len(daily_rets) // 2),
            color="#22c55e",
            alpha=0.7,
            edgecolor="#1e293b",
        )
        ax.axvline(0, color="#ef4444", linewidth=1, linestyle="--")
        ax.set_title("Daily Returns Distribution", color="#f8fafc", fontweight="bold")
        ax.set_xlabel("Return %", color="#94a3b8")
        ax.set_ylabel("Frequency", color="#94a3b8")
        ax.set_facecolor("#1e293b")
        fig.patch.set_facecolor("#0f172a")
        ax.tick_params(colors="#94a3b8")
        ax.spines["bottom"].set_color("#334155")
        ax.spines["left"].set_color("#334155")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(True, alpha=0.15, color="#334155")
        charts_html += f'<img src="{_fig_to_b64(fig)}" style="width:100%;border-radius:8px;margin-top:12px;" alt="Daily Returns">'

    return charts_html


def build_html(portfolio: dict) -> str:
    _load_universe()
    history = portfolio.get("iterations_log", [])
    positions = portfolio.get("current_positions", {})
    metadata = portfolio.get("metadata", {})
    cash = metadata.get("current_cash", 0)
    metrics = _compute_metrics(history)
    total_eur = metrics.get("final", cash)
    m = metrics

    metric_cards = f"""
    <div class="metric-grid">
      <div class="card"><div class="val">{m.get("total_return", 0):.2f}%</div><div class="lbl">Total Return</div></div>
      <div class="card"><div class="val">{m.get("ann_return", 0):.2f}%</div><div class="lbl">Ann. Return</div></div>
      <div class="card"><div class="val">{m.get("ann_vol", 0):.2f}%</div><div class="lbl">Ann. Volatility</div></div>
      <div class="card"><div class="val">{m.get("sharpe", 0):.2f}</div><div class="lbl">Sharpe</div></div>
      <div class="card"><div class="val" style="color:#ef4444">{m.get("max_drawdown", 0):.2f}%</div><div class="lbl">Max DD</div></div>
      <div class="card"><div class="val">{m.get("calmar", 0):.2f}</div><div class="lbl">Calmar</div></div>
      <div class="card"><div class="val">{m.get("win_rate", 0):.1f}%</div><div class="lbl">Win Rate</div></div>
      <div class="card"><div class="val">{m.get("profit_factor", 0):.2f}</div><div class="lbl">Profit Factor</div></div>
    </div>"""

    pos_rows = ""
    for ticker in sorted(positions.keys()):
        p = positions[ticker]
        info = UNIVERSE.get(ticker, {})
        last_prices = history[-1].get("prices_used", {}) if history else {}
        cur_price = last_prices.get(ticker, p["avg_price"])
        cur_price_eur = cur_price
        ccy = info.get("currency", "")
        if ccy == "USD":
            cur_price_eur = cur_price * 0.8663
        elif ccy == "GBP":
            cur_price_eur = cur_price * 1.17
        eq = p["shares"] * cur_price_eur
        cost = p["shares"] * p["avg_price"]
        pnl_e = eq - cost
        pnl_p = (
            ((cur_price_eur / p["avg_price"]) - 1) * 100 if p["avg_price"] > 0 else 0
        )
        pnl_class = "neg" if pnl_e < 0 else "pos"
        pos_rows += f"""<tr><td><strong>{ticker}</strong></td><td>{info.get("exchange", "")}</td>
        <td>{info.get("sector", "")}</td><td>{ccy}</td><td>{p["shares"]}</td>
        <td>{p["avg_price"]:.2f}</td><td>{cur_price_eur:.2f}</td><td>{eq:.2f}</td>
        <td class="{pnl_class}">{pnl_e:+.2f}</td><td class="{pnl_class}">{pnl_p:+.2f}%</td></tr>"""

    tx_rows = ""
    for e in reversed(history):
        for tx in e.get("transactions", []):
            a = tx["action"]
            cls = "tx-buy" if a == "BUY" else "tx-sell"
            tx_rows += f"""<tr><td>{e.get("timestamp", "")[:16]}</td>
            <td class="{cls}">{a}</td><td><strong>{tx["ticker"]}</strong></td>
            <td>{tx["shares"]}</td><td>{tx.get("price_eur", 0):.2f}</td>
            <td>{tx.get("total_cost_eur", tx.get("total_proceeds_eur", 0)):.2f}</td></tr>"""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    charts_b64 = generate_charts_html(portfolio)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Paper Trading Dashboard</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0f172a; color:#e2e8f0; }}
.header {{ background:linear-gradient(135deg,#1e293b,#0f172a); padding:24px 32px; border-bottom:1px solid #334155; }}
.header h1 {{ font-size:24px; font-weight:700; color:#f8fafc; }}
.header p {{ color:#94a3b8; font-size:13px; margin-top:4px; }}
.container {{ max-width:1200px; margin:0 auto; padding:24px; }}
.metric-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; margin-bottom:24px; }}
.card {{ background:#1e293b; border:1px solid #334155; border-radius:10px; padding:16px; text-align:center; }}
.card .val {{ font-size:22px; font-weight:700; color:#22c55e; }}
.card .lbl {{ font-size:11px; color:#94a3b8; margin-top:4px; text-transform:uppercase; letter-spacing:0.5px; }}
.charts {{ margin-bottom:24px; }}
.charts img {{ max-width:100%; height:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#334155; color:#94a3b8; text-align:left; padding:8px 10px; font-weight:600; text-transform:uppercase; font-size:11px; letter-spacing:0.5px; }}
td {{ padding:8px 10px; border-bottom:1px solid #1e293b; }}
tr:hover td {{ background:#1e293b; }}
.pos {{ color:#22c55e; }} .neg {{ color:#ef4444; }}
.tx-buy {{ color:#22c55e; font-weight:600; }} .tx-sell {{ color:#ef4444; font-weight:600; }}
.section-title {{ font-size:16px; font-weight:600; margin:24px 0 12px; color:#f1f5f9; }}
@media(max-width:768px){{ .metric-grid {{ grid-template-columns:repeat(2,1fr); }} }}
</style>
</head>
<body>
<div class="header">
  <h1>Paper Trading Dashboard</h1>
  <p>Aggiornato: {now} &middot; Capitale: {metadata.get("initial_capital", 0):.0f} EUR &middot; NASDAQ, NYSE, FTSE, BIT</p>
</div>
<div class="container">
  {metric_cards}
  <div class="charts">{charts_b64}</div>
  <div class="section-title">Posizioni Aperte ({len(positions)})</div>
  <div style="overflow-x:auto;"><table><thead><tr><th>Ticker</th><th>Exc</th><th>Sector</th><th>CCY</th><th>Shares</th><th>Avg</th><th>Cur</th><th>Equity</th><th>PnL</th><th>PnL%</th></tr></thead>
    <tbody>{pos_rows}</tbody></table></div>
  <div class="section-title">Transazioni ({history[-1].get("transactions", []) and "varie" or "0"})</div>
  <div style="overflow-x:auto;max-height:400px;overflow-y:auto;"><table><thead><tr><th>Date</th><th>Action</th><th>Ticker</th><th>Shares</th><th>Price</th><th>Total</th></tr></thead>
    <tbody>{tx_rows}</tbody></table></div>
</div>
</body>
</html>"""
