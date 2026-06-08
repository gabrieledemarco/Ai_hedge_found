import json
import math
import base64
import io
import os
from datetime import datetime, timezone
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

UNIVERSE: dict[str, dict] = {}

PORTFOLIO_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "portfolio_history.json"
)


def _load_universe():
    global UNIVERSE
    if not UNIVERSE:
        import sys

        root = os.path.join(os.path.dirname(__file__), "..")
        sys.path.insert(0, root)
        sys.path.insert(0, os.path.join(root, "scripts"))
        from main_pipeline import UNIVERSE as U

        UNIVERSE = U


def load_portfolio() -> dict[str, Any]:
    with open(PORTFOLIO_PATH) as f:
        return json.load(f)


def _fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#0f172a")
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return f"data:image/png;base64,{data}"


def _convert_price(price: float, currency: str) -> float:
    if currency == "USD":
        return price * 0.9200
    if currency == "GBP":
        return price * 1.1700
    return price


def _compute_metrics(history: list[dict]) -> dict[str, Any]:
    if not history:
        return {}
    values = [e["total_value_eur"] for e in history]
    initial = history[0].get("total_value_eur", values[0])
    final = values[-1]
    total_return = (final - initial) / initial * 100
    n = len(values)

    daily_rets = []
    for i in range(1, len(values)):
        daily_rets.append((values[i] - values[i - 1]) / values[i - 1] * 100)
    n_days = len(daily_rets)

    avg_daily_ret = sum(daily_rets) / n_days if n_days > 0 else 0
    daily_vol = (
        math.sqrt(sum((r - avg_daily_ret) ** 2 for r in daily_rets) / n_days)
        if n_days > 0
        else 0
    )
    ann_return = total_return / n * 252 if n > 0 else 0
    ann_vol = daily_vol * math.sqrt(252)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0

    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd
    calmar = ann_return / max_dd if max_dd > 0 else 0

    gains = [r for r in daily_rets if r > 0]
    losses = [r for r in daily_rets if r < 0]
    win_rate = len(gains) / n_days * 100 if n_days > 0 else 0
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
        "profit_factor": profit_factor,
        "n_entries": n,
        "values": values,
    }


def build_live_html(portfolio: dict, live_prices: dict[str, float]) -> str:
    _load_universe()
    history = portfolio.get("iterations_log", [])
    positions = portfolio.get("current_positions", {})
    metadata = portfolio.get("metadata", {})
    cash = metadata.get("current_cash", 0)

    total_eur = cash
    pos_equity: dict[str, float] = {}
    for ticker, p in positions.items():
        cur = live_prices.get(ticker, p["avg_price"])
        ccy = UNIVERSE.get(ticker, {}).get("currency", "EUR")
        cur_eur = _convert_price(cur, ccy)
        eq = p["shares"] * cur_eur
        pos_equity[ticker] = eq
        total_eur += eq

    m = _compute_metrics(history)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

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

    chart_html = ""
    timestamps = [e["timestamp"] for e in history] if history else []
    values = m.get("values", [])
    cash_hist = [e["current_cash"] for e in history] if history else []

    # --- Equity Curve ---
    fig, ax = plt.subplots(figsize=(10, 3.2))
    if timestamps:
        ts = [datetime.fromisoformat(t) for t in timestamps]
        ax.plot(ts, values, color="#22c55e", linewidth=2)
        ax.fill_between(ts, values, alpha=0.1, color="#22c55e")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.set_title("Equity Curve - Portfolio", color="#f8fafc", fontweight="bold")
    ax.set_facecolor("#1e293b")
    fig.patch.set_facecolor("#0f172a")
    ax.tick_params(colors="#94a3b8")
    ax.spines["bottom"].set_color("#334155")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, alpha=0.15, color="#334155")
    ax.set_ylabel("EUR", color="#94a3b8")
    chart_html += '<div style="display:flex;gap:12px;flex-wrap:wrap;">'
    chart_html += f'<div style="flex:1;min-width:300px;"><img src="{_fig_to_b64(fig)}" style="width:100%;border-radius:8px;" alt="Equity Curve - Portfolio"></div>'

    # --- Cash ---
    fig, ax = plt.subplots(figsize=(10, 3.2))
    if timestamps:
        ts = [datetime.fromisoformat(t) for t in timestamps]
        ax.plot(ts, cash_hist, color="#3b82f6", linewidth=2)
        ax.fill_between(ts, cash_hist, alpha=0.1, color="#3b82f6")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.set_title("Cash", color="#f8fafc", fontweight="bold")
    ax.set_facecolor("#1e293b")
    fig.patch.set_facecolor("#0f172a")
    ax.tick_params(colors="#94a3b8")
    ax.spines["bottom"].set_color("#334155")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, alpha=0.15, color="#334155")
    ax.set_ylabel("EUR", color="#94a3b8")
    chart_html += f'<div style="flex:1;min-width:300px;"><img src="{_fig_to_b64(fig)}" style="width:100%;border-radius:8px;" alt="Cash"></div>'
    chart_html += "</div>"

    # --- Allocation + Sector ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.2))
    if positions:
        labels = sorted(positions.keys())
        sizes = [positions[t]["shares"] for t in labels]
        colors_al = plt.cm.Set3(range(len(labels)))
        wedges, _, autotexts = ax1.pie(
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
    for t, eq in pos_equity.items():
        sec = UNIVERSE.get(t, {}).get("sector", "Other")
        sector_values[sec] = sector_values.get(sec, 0) + eq
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
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.grid(True, alpha=0.15, axis="x", color="#334155")
    fig.patch.set_facecolor("#0f172a")
    chart_html += f'<img src="{_fig_to_b64(fig)}" style="width:100%;border-radius:8px;margin-top:12px;" alt="Allocation and Sector">'

    # --- Drawdown + PnL Live ---
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
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.grid(True, alpha=0.15, color="#334155")
    ax1.set_ylabel("%", color="#94a3b8")

    pnl_tickers: list[str] = []
    pnl_values: list[float] = []
    pnl_colors: list[str] = []
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
    ax2.set_title(
        "PnL Live (based on live prices)",
        color="#f8fafc",
        fontweight="bold",
        fontsize=10,
    )
    ax2.set_facecolor("#1e293b")
    ax2.tick_params(colors="#94a3b8")
    ax2.spines["bottom"].set_color("#334155")
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.axvline(0, color="#94a3b8", linewidth=0.5)
    ax2.grid(True, alpha=0.15, axis="x", color="#334155")
    fig.patch.set_facecolor("#0f172a")
    chart_html += f'<img src="{_fig_to_b64(fig)}" style="width:100%;border-radius:8px;margin-top:12px;" alt="Drawdown and PnL Live">'

    # --- Daily Returns ---
    daily_rets = []
    for i in range(1, len(values)):
        daily_rets.append((values[i] - values[i - 1]) / values[i - 1] * 100)
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
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(True, alpha=0.15, color="#334155")
        chart_html += f'<img src="{_fig_to_b64(fig)}" style="width:100%;border-radius:8px;margin-top:12px;" alt="Daily Returns">'

    # --- Positions table ---
    pos_rows = ""
    for ticker in sorted(positions.keys()):
        p = positions[ticker]
        info = UNIVERSE.get(ticker, {})
        cur = live_prices.get(ticker, p["avg_price"])
        ccy = info.get("currency", "")
        cur_eur = _convert_price(cur, ccy)
        eq = p["shares"] * cur_eur
        cost = p["shares"] * p["avg_price"]
        pnl_e = eq - cost
        pnl_p = ((cur_eur / p["avg_price"]) - 1) * 100 if p["avg_price"] > 0 else 0
        pnl_class = "neg" if pnl_e < 0 else "pos"
        pos_rows += f"""<tr><td><strong>{ticker}</strong></td><td>{info.get("exchange", "")}</td>
        <td>{info.get("sector", "")}</td><td>{ccy}</td><td>{p["shares"]}</td>
        <td>{p["avg_price"]:.2f}</td><td>{cur_eur:.2f}</td><td>{eq:.2f}</td>
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

    total_label = "LIVE" if live_prices else "STALE"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Paper Trading Dashboard - Live</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0f172a; color:#e2e8f0; }}
.header {{ background:linear-gradient(135deg,#1e293b,#0f172a); padding:24px 32px; border-bottom:1px solid #334155; }}
.header h1 {{ font-size:24px; font-weight:700; color:#f8fafc; }}
.header p {{ color:#94a3b8; font-size:13px; margin-top:4px; }}
.badge {{ display:inline-block; background:#22c55e; color:#0f172a; font-size:11px; font-weight:700; padding:2px 8px; border-radius:4px; margin-left:8px; }}
.container {{ max-width:1200px; margin:0 auto; padding:24px; }}
.metric-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; margin-bottom:24px; }}
.card {{ background:#1e293b; border:1px solid #334155; border-radius:10px; padding:16px; text-align:center; }}
.card .val {{ font-size:22px; font-weight:700; color:#22c55e; }}
.card .lbl {{ font-size:11px; color:#94a3b8; margin-top:4px; text-transform:uppercase; letter-spacing:0.5px; }}
.charts img {{ max-width:100%; height:auto; margin-bottom:12px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#334155; color:#94a3b8; text-align:left; padding:8px 10px; font-weight:600; text-transform:uppercase; font-size:11px; letter-spacing:0.5px; }}
td {{ padding:8px 10px; border-bottom:1px solid #1e293b; }}
tr:hover td {{ background:#1e293b; }}
.pos {{ color:#22c55e; }} .neg {{ color:#ef4444; }}
.tx-buy {{ color:#22c55e; font-weight:600; }} .tx-sell {{ color:#ef4444; font-weight:600; }}
.section-title {{ font-size:16px; font-weight:600; margin:24px 0 12px; color:#f1f5f9; }}
.refresh-note {{ text-align:center; color:#64748b; font-size:12px; margin-top:8px; }}
@media(max-width:768px){{ .metric-grid {{ grid-template-columns:repeat(2,1fr); }} }}
</style>
</head>
<body>
<div class="header">
  <h1>Paper Trading Dashboard <span class="badge">{total_label}</span></h1>
  <p>{now} &middot; Capitale: {metadata.get("initial_capital", 0):.0f} EUR &middot; Prezzi yfinance live</p>
</div>
<div class="container">
  {metric_cards}
  <div class="charts">{chart_html}</div>
  <div class="section-title">Posizioni Aperte ({len(positions)})</div>
  <div style="overflow-x:auto;"><table><thead><tr><th>Ticker</th><th>Exc</th><th>Sector</th><th>CCY</th><th>Shares</th><th>Avg</th><th>Live Price</th><th>Equity</th><th>PnL Live</th><th>PnL%</th></tr></thead>
    <tbody>{pos_rows}</tbody></table></div>
  <div class="section-title">Transazioni</div>
  <div style="overflow-x:auto;max-height:400px;overflow-y:auto;"><table><thead><tr><th>Date</th><th>Action</th><th>Ticker</th><th>Shares</th><th>Price</th><th>Total</th></tr></thead>
    <tbody>{tx_rows}</tbody></table></div>
  <p class="refresh-note">I prezzi vengono aggiornati da yfinance ad ogni caricamento pagina. Cache: 60s.</p>
</div>
</body>
</html>"""
