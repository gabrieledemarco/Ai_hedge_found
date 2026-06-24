import os
import sys
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

sys.path.insert(0, os.path.dirname(__file__))

DASHBOARD_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "index.html")

STRATEGY_COLORS = {
    "equal_weight": "#22c55e",
    "momentum": "#3b82f6",
    "fundamental": "#f59e0b",
    "sentiment": "#a855f7",
}

STRATEGY_LABELS = {
    "equal_weight": "Equal Weight",
    "momentum": "Momentum",
    "fundamental": "Fundamental",
    "sentiment": "Sentiment",
}


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _calc_daily_returns(values: list) -> list:
    if len(values) < 2:
        return []
    return [
        (values[i] - values[i - 1]) / values[i - 1] * 100 for i in range(1, len(values))
    ]


def _calc_max_drawdown(values: list) -> float:
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _compute_metrics(history: list) -> dict:
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
        "initial": initial,
        "final": final,
        "daily_rets": daily_rets,
        "values": values,
    }


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#0f172a")
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return f"data:image/png;base64,{data}"


def _dark_ax(ax):
    """Apply dark theme to a matplotlib axes."""
    ax.set_facecolor("#1e293b")
    ax.tick_params(colors="#94a3b8")
    ax.spines["bottom"].set_color("#334155")
    ax.spines["left"].set_color("#334155")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, alpha=0.15, color="#334155")


# ---------------------------------------------------------------------------
# Chart generators
# ---------------------------------------------------------------------------

def _generate_equity_comparison_chart(portfolios: dict) -> str:
    """Multi-strategy equity curve comparison chart."""
    fig, ax = plt.subplots(figsize=(11, 3.5))
    has_data = False
    for sname, portfolio in portfolios.items():
        history = portfolio.get("iterations_log", [])
        if not history:
            continue
        timestamps = []
        values = []
        for e in history:
            try:
                timestamps.append(datetime.fromisoformat(e["timestamp"]))
                values.append(e["total_value_eur"])
            except (ValueError, KeyError):
                continue
        if timestamps:
            color = STRATEGY_COLORS.get(sname, "#94a3b8")
            label = STRATEGY_LABELS.get(sname, sname)
            ax.plot(timestamps, values, color=color, linewidth=2, label=label)
            has_data = True

    if not has_data:
        ax.text(0.5, 0.5, "No data yet — in attesa della prima sessione di trading",
                ha="center", va="center", transform=ax.transAxes, color="#94a3b8")

    ax.set_title("Strategy Performance Comparison", color="#f8fafc", fontweight="bold")
    ax.set_ylabel("EUR", color="#94a3b8")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    if has_data:
        legend = ax.legend(loc="upper left", fontsize=9, fancybox=False,
                           framealpha=0.3, labelcolor="#e2e8f0")
        legend.get_frame().set_facecolor("#1e293b")
        legend.get_frame().set_edgecolor("#334155")
    fig.patch.set_facecolor("#0f172a")
    _dark_ax(ax)
    return _fig_to_b64(fig)


def _generate_single_equity_chart(portfolio: dict, strategy_name: str) -> str:
    """Single strategy equity + cash chart."""
    history = portfolio.get("iterations_log", [])
    color = STRATEGY_COLORS.get(strategy_name, "#22c55e")
    fig, ax = plt.subplots(figsize=(10, 3))
    if history:
        ts = []
        vals = []
        cash_vals = []
        for e in history:
            try:
                ts.append(datetime.fromisoformat(e["timestamp"]))
                vals.append(e["total_value_eur"])
                cash_vals.append(e.get("current_cash", 0))
            except (ValueError, KeyError):
                continue
        if ts:
            ax.plot(ts, vals, color=color, linewidth=2, label="Portfolio")
            ax.fill_between(ts, vals, alpha=0.1, color=color)
            ax.plot(ts, cash_vals, color="#64748b", linewidth=1, linestyle="--", label="Cash")
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.set_title(
        f"Equity Curve — {STRATEGY_LABELS.get(strategy_name, strategy_name)}",
        color="#f8fafc", fontweight="bold"
    )
    ax.set_ylabel("EUR", color="#94a3b8")
    legend = ax.legend(loc="upper left", fontsize=8, fancybox=False,
                       framealpha=0.3, labelcolor="#e2e8f0")
    legend.get_frame().set_facecolor("#1e293b")
    legend.get_frame().set_edgecolor("#334155")
    fig.patch.set_facecolor("#0f172a")
    _dark_ax(ax)
    return _fig_to_b64(fig)


# ---------------------------------------------------------------------------
# HTML Section builders
# ---------------------------------------------------------------------------

def _build_strategy_cards(portfolios: dict) -> str:
    """4 strategy cards side by side."""
    cards = ""
    for sname in ["equal_weight", "momentum", "fundamental", "sentiment"]:
        portfolio = portfolios.get(sname, {})
        history = portfolio.get("iterations_log", [])
        metadata = portfolio.get("metadata", {})
        metrics = _compute_metrics(history)
        initial = metadata.get("initial_capital", 3000.0)
        total = metrics.get("final", metadata.get("current_cash", initial))
        ret_pct = metrics.get("total_return", 0.0)
        color = STRATEGY_COLORS.get(sname, "#22c55e")
        label = STRATEGY_LABELS.get(sname, sname)
        sign = "+" if ret_pct >= 0 else ""
        badge_cls = "badge-pos" if ret_pct >= 0 else "badge-neg"

        # daily change from last 2 entries
        values = metrics.get("values", [])
        daily_chg = 0.0
        if len(values) >= 2:
            daily_chg = (values[-1] - values[-2]) / values[-2] * 100 if values[-2] > 0 else 0
        daily_sign = "+" if daily_chg >= 0 else ""
        daily_cls = "pos" if daily_chg >= 0 else "neg"

        cards += f"""
        <div class="strategy-card" style="border-top:3px solid {color};">
          <div class="strat-name">{label}</div>
          <div class="strat-value">{total:.2f} EUR</div>
          <div class="strat-return {badge_cls}">{sign}{ret_pct:.2f}%</div>
          <div class="strat-daily {daily_cls}">1d: {daily_sign}{daily_chg:.2f}%</div>
        </div>"""
    return f'<div class="strategy-cards">{cards}</div>'


def _build_screener_table(signals: dict) -> str:
    """Stock screener table with composite scores."""
    try:
        from config import UNIVERSE
    except ImportError:
        return "<p style='color:#94a3b8'>Screener unavailable (config not found)</p>"

    sentiment_data = signals.get("sentiment", {})
    fundamentals_data = signals.get("fundamentals", {})
    momentum_data = signals.get("momentum", {})

    rows_data = []
    for ticker, info in UNIVERSE.items():
        sent = sentiment_data.get(ticker, {})
        fund = fundamentals_data.get(ticker, {})
        mom = momentum_data.get(ticker, {})

        sent_score = sent.get("score", 0.0)      # [-1, 1]
        f_score = fund.get("f_score", 0.5)        # [0, 1]
        ret_3m = mom.get("return_3m", 0.0)        # float, e.g. 0.12 = 12%

        # Normalize momentum to [0, 1]: clamp to [-0.3, +0.3] range
        mom_norm = max(0.0, min(1.0, (ret_3m + 0.3) / 0.6))
        # Normalize sentiment from [-1,1] to [0,1]
        sent_norm = (sent_score + 1.0) / 2.0

        composite = 0.35 * sent_norm + 0.35 * f_score + 0.30 * mom_norm

        sent_label = sent.get("label", "Neutral")
        if sent_label.lower() == "bullish":
            sent_cls = "pos"
        elif sent_label.lower() == "bearish":
            sent_cls = "neg"
        else:
            sent_cls = "neutral-lbl"

        rows_data.append({
            "ticker": ticker,
            "exchange": info.get("exchange", ""),
            "sector": info.get("sector", ""),
            "ret_3m": ret_3m,
            "f_score": f_score,
            "sent_score": sent_score,
            "sent_label": sent_label,
            "sent_cls": sent_cls,
            "composite": composite,
        })

    rows_data.sort(key=lambda x: x["composite"], reverse=True)

    rows_html = ""
    for r in rows_data:
        ret_cls = "pos" if r["ret_3m"] >= 0 else "neg"
        comp_pct = int(r["composite"] * 100)
        comp_bar = f'<div style="background:#334155;border-radius:3px;height:6px;width:80px;display:inline-block;vertical-align:middle;"><div style="background:#22c55e;height:6px;border-radius:3px;width:{comp_pct}%;"></div></div>'
        fscore_pct = int(r["f_score"] * 100)
        fscore_bar = f'<div style="background:#334155;border-radius:3px;height:6px;width:60px;display:inline-block;vertical-align:middle;"><div style="background:#f59e0b;height:6px;border-radius:3px;width:{fscore_pct}%;"></div></div>'
        ret_sign = "+" if r["ret_3m"] >= 0 else ""
        sent_sign = "+" if r["sent_score"] >= 0 else ""
        rows_html += f"""<tr>
          <td><strong>{r['ticker']}</strong></td>
          <td>{r['exchange']}</td>
          <td>{r['sector']}</td>
          <td class="{ret_cls}">{ret_sign}{r['ret_3m']*100:.1f}%</td>
          <td>{fscore_bar} {r['f_score']:.2f}</td>
          <td class="{r['sent_cls']}">{sent_sign}{r['sent_score']:.3f} <small>{r['sent_label']}</small></td>
          <td>{comp_bar} {r['composite']:.3f}</td>
        </tr>"""

    return f"""
    <div style="overflow-x:auto;">
    <table>
      <thead><tr>
        <th>Ticker</th><th>Exchange</th><th>Sector</th>
        <th>Mom 3m</th><th>F-Score</th><th>Sentiment</th><th>Composite</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    </div>"""


def _build_portfolio_tabs(portfolios: dict) -> str:
    """Tab-based portfolio detail for each strategy."""
    try:
        from config import UNIVERSE
    except ImportError:
        UNIVERSE = {}

    tab_buttons = ""
    tab_panels = ""

    strategy_order = ["equal_weight", "momentum", "fundamental", "sentiment"]
    for idx, sname in enumerate(strategy_order):
        portfolio = portfolios.get(sname, {})
        if not portfolio:
            continue
        label = STRATEGY_LABELS.get(sname, sname)
        active_btn = "tab-btn active" if idx == 0 else "tab-btn"
        active_panel = "tab-panel active" if idx == 0 else "tab-panel"

        history = portfolio.get("iterations_log", [])
        positions = portfolio.get("current_positions", {})
        last_prices = history[-1].get("prices_used", {}) if history else {}
        metadata = portfolio.get("metadata", {})

        # Generate equity chart
        chart_b64 = _generate_single_equity_chart(portfolio, sname)

        pos_rows = ""
        for ticker in sorted(positions.keys()):
            p = positions[ticker]
            info = UNIVERSE.get(ticker, {})
            cur_price_local = last_prices.get(ticker, p["avg_price"])
            ccy = info.get("currency", "EUR")
            fx = {"USD": 0.92, "GBP": 1.17, "GBp": 0.0117, "EUR": 1.0}.get(ccy, 1.0)
            cur_price_eur = cur_price_local * fx
            eq = p["shares"] * cur_price_eur
            cost = p["shares"] * p["avg_price"]
            pnl_e = eq - cost
            pnl_p = ((cur_price_eur / p["avg_price"]) - 1) * 100 if p["avg_price"] > 0 else 0
            pnl_cls = "pos" if pnl_e >= 0 else "neg"
            pos_rows += f"""<tr>
              <td><strong>{ticker}</strong></td>
              <td>{info.get('exchange', '')}</td>
              <td>{p['shares']}</td>
              <td>{p['avg_price']:.2f}</td>
              <td>{cur_price_eur:.2f}</td>
              <td>{eq:.2f}</td>
              <td class="{pnl_cls}">{pnl_e:+.2f}</td>
              <td class="{pnl_cls}">{pnl_p:+.2f}%</td>
            </tr>"""

        metrics = _compute_metrics(history)
        cash = metadata.get("current_cash", 0)
        total = metrics.get("final", cash)
        initial = metadata.get("initial_capital", 3000.0)
        ret_pct = metrics.get("total_return", 0.0)

        tab_buttons += f'<button class="{active_btn}" onclick="showTab(\'{sname}\')" id="btn-{sname}">{label}</button>'
        tab_panels += f"""
        <div class="{active_panel}" id="panel-{sname}">
          <div class="tab-summary">
            <span>Total: <strong>{total:.2f} EUR</strong></span>
            <span>Cash: <strong>{cash:.2f} EUR</strong></span>
            <span>Return: <strong class="{'pos' if ret_pct >= 0 else 'neg'}">{ret_pct:+.2f}%</strong></span>
            <span>Positions: <strong>{len(positions)}</strong></span>
          </div>
          <img src="{chart_b64}" style="width:100%;border-radius:8px;margin:12px 0;" alt="Equity {label}">
          {'<div style="overflow-x:auto;"><table><thead><tr><th>Ticker</th><th>Exc</th><th>Shares</th><th>Avg</th><th>Cur</th><th>Equity</th><th>PnL</th><th>PnL%</th></tr></thead><tbody>' + pos_rows + '</tbody></table></div>' if pos_rows else '<p style="color:#64748b;padding:12px 0">No positions yet.</p>'}
        </div>"""

    return f"""
    <div class="tabs">
      <div class="tab-buttons">{tab_buttons}</div>
      {tab_panels}
    </div>"""


# ---------------------------------------------------------------------------
# Main HTML builder
# ---------------------------------------------------------------------------

def build_html(portfolios: dict, signals: dict = None) -> str:
    """
    Build the multi-portfolio HTML dashboard.
    portfolios: {strategy_name: portfolio_dict}
    signals: signals.json content (optional)
    """
    if signals is None:
        signals = {}

    try:
        from config import UNIVERSE
    except ImportError:
        UNIVERSE = {}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    signals_updated = signals.get("fundamentals_updated", "N/A")
    sentiment_updated = signals.get("sentiment_updated", "N/A")
    if signals_updated != "N/A":
        signals_updated = signals_updated[:16].replace("T", " ")
    if sentiment_updated != "N/A":
        sentiment_updated = sentiment_updated[:16].replace("T", " ")

    strategy_cards_html = _build_strategy_cards(portfolios)
    comparison_chart = _generate_equity_comparison_chart(portfolios)
    screener_html = _build_screener_table(signals)
    portfolio_tabs_html = _build_portfolio_tabs(portfolios)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Hedge Fund — Multi-Strategy Dashboard</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0f172a; color:#e2e8f0; }}
a {{ color:#38bdf8; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.header {{ background:linear-gradient(135deg,#1e293b,#0f172a); padding:24px 32px; border-bottom:1px solid #334155; }}
.header h1 {{ font-size:22px; font-weight:700; color:#f8fafc; }}
.header .sub {{ color:#94a3b8; font-size:12px; margin-top:6px; display:flex; gap:16px; flex-wrap:wrap; }}
.container {{ max-width:1280px; margin:0 auto; padding:24px; }}
.section-title {{ font-size:15px; font-weight:700; margin:28px 0 12px; color:#f1f5f9; text-transform:uppercase; letter-spacing:0.5px; border-left:3px solid #334155; padding-left:10px; }}

/* Strategy cards */
.strategy-cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin-bottom:28px; }}
.strategy-card {{ background:#1e293b; border:1px solid #334155; border-radius:10px; padding:18px; }}
.strat-name {{ font-size:11px; text-transform:uppercase; letter-spacing:0.8px; color:#94a3b8; margin-bottom:8px; }}
.strat-value {{ font-size:22px; font-weight:700; color:#f8fafc; }}
.strat-return {{ font-size:14px; font-weight:600; margin-top:4px; display:inline-block; padding:2px 8px; border-radius:4px; }}
.badge-pos {{ background:rgba(34,197,94,0.15); color:#22c55e; }}
.badge-neg {{ background:rgba(239,68,68,0.15); color:#ef4444; }}
.strat-daily {{ font-size:12px; margin-top:4px; color:#64748b; }}

/* Comparison chart */
.chart-wrap {{ background:#1e293b; border:1px solid #334155; border-radius:10px; padding:16px; margin-bottom:28px; }}
.chart-wrap img {{ width:100%; border-radius:6px; }}

/* Screener table */
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#1e293b; color:#64748b; text-align:left; padding:9px 10px; font-weight:600; text-transform:uppercase; font-size:10px; letter-spacing:0.5px; border-bottom:1px solid #334155; }}
td {{ padding:8px 10px; border-bottom:1px solid #1a2332; }}
tr:hover td {{ background:#1e293b; }}
.pos {{ color:#22c55e; }} .neg {{ color:#ef4444; }} .neutral-lbl {{ color:#94a3b8; }}

/* Tabs */
.tabs {{ background:#1e293b; border:1px solid #334155; border-radius:10px; overflow:hidden; }}
.tab-buttons {{ display:flex; gap:0; background:#0f172a; border-bottom:1px solid #334155; flex-wrap:wrap; }}
.tab-btn {{ background:transparent; border:none; color:#64748b; padding:12px 20px; cursor:pointer; font-size:13px; font-weight:500; transition:all .15s; border-bottom:2px solid transparent; }}
.tab-btn:hover {{ color:#e2e8f0; background:#1e293b; }}
.tab-btn.active {{ color:#f8fafc; border-bottom-color:#38bdf8; }}
.tab-panel {{ display:none; padding:20px; }}
.tab-panel.active {{ display:block; }}
.tab-summary {{ display:flex; gap:20px; flex-wrap:wrap; margin-bottom:12px; font-size:13px; color:#94a3b8; }}
.tab-summary strong {{ color:#f8fafc; }}

/* Footer */
.footer {{ text-align:center; padding:24px; color:#475569; font-size:12px; border-top:1px solid #1e293b; margin-top:28px; }}

@media(max-width:768px) {{ .strategy-cards {{ grid-template-columns:repeat(2,1fr); }} }}
</style>
</head>
<body>
<div class="header">
  <h1>AI Hedge Fund &mdash; Multi-Strategy Paper Trading</h1>
  <div class="sub">
    <span>Updated: <strong>{now}</strong></span>
    <span>Signals: <strong>{signals_updated}</strong></span>
    <span>Sentiment: <strong>{sentiment_updated}</strong></span>
    <span>Exchanges: NASDAQ &middot; NYSE &middot; FTSE &middot; BIT</span>
  </div>
</div>

<div class="container">

  <div class="section-title">Strategy Overview</div>
  {strategy_cards_html}

  <div class="section-title">Performance Comparison</div>
  <div class="chart-wrap">
    <img src="{comparison_chart}" alt="Strategy Comparison">
  </div>

  <div class="section-title">Stock Screener</div>
  <div style="background:#1e293b;border:1px solid #334155;border-radius:10px;overflow:hidden;margin-bottom:28px;">
    {screener_html}
  </div>

  <div class="section-title">Portfolio Details</div>
  {portfolio_tabs_html}

</div>

<div class="footer">
  <a href="https://github.com">GitHub</a> &middot;
  AI Hedge Fund Paper Trading &middot; {now}
</div>

<script>
function showTab(name) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  var panel = document.getElementById('panel-' + name);
  var btn = document.getElementById('btn-' + name);
  if (panel) panel.classList.add('active');
  if (btn) btn.classList.add('active');
}}
</script>
</body>
</html>"""
