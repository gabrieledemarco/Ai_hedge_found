"""
Live dashboard HTML generator for the Flask web app (Render.com).
Loads all 4 strategy portfolios, applies live prices, renders dark-theme HTML.

Fixes applied vs original:
  - UNIVERSE imported from config (not main_pipeline)
  - FX rates from config.FX_FALLBACK (consistent with pipeline)
  - datetime.fromisoformat handles Z-suffix (Python < 3.11 compat)
  - Pie chart ax1.set_facecolor for dark theme
  - Multi-portfolio: loads all 4 strategies, shows comparison + tabs
  - /health and /api/portfolios now cover all strategies
"""

import base64
import io
import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from config import UNIVERSE, STRATEGIES, STRATEGY_LABELS, FX_FALLBACK, INITIAL_CAPITAL

PORTFOLIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "portfolios")
LEGACY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio_history.json")

STRATEGY_COLORS = {
    "equal_weight": "#22c55e",
    "momentum": "#3b82f6",
    "fundamental": "#f59e0b",
    "sentiment": "#a855f7",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ts(ts: str) -> datetime:
    """Parse ISO timestamp, handling Z-suffix (Python < 3.11 compat)."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _to_eur(price: float, currency: str) -> float:
    return price * FX_FALLBACK.get(currency, 1.0)


def _fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#0f172a")
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return f"data:image/png;base64,{data}"


def _dark_ax(ax: plt.Axes) -> None:
    ax.set_facecolor("#1e293b")
    ax.tick_params(colors="#94a3b8")
    for spine in ax.spines.values():
        spine.set_color("#334155")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, alpha=0.15, color="#334155")


# ── Portfolio loading ─────────────────────────────────────────────────────────

def load_all_portfolios() -> dict[str, Any]:
    """Load all 4 strategy portfolios. Falls back to legacy for equal_weight."""
    portfolios = {}
    for name in STRATEGIES:
        path = os.path.join(PORTFOLIOS_DIR, f"{name}.json")
        try:
            with open(path) as f:
                portfolios[name] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            if name == "equal_weight":
                try:
                    with open(LEGACY_PATH) as f:
                        portfolios[name] = json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
            if name not in portfolios:
                portfolios[name] = {
                    "strategy": name,
                    "metadata": {"initial_capital": INITIAL_CAPITAL, "current_cash": INITIAL_CAPITAL},
                    "current_positions": {},
                    "iterations_log": [],
                }
    return portfolios


def load_portfolio() -> dict[str, Any]:
    """Legacy single-portfolio loader (backward compat)."""
    try:
        with open(LEGACY_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return load_all_portfolios().get("equal_weight", {})


# ── Metrics ───────────────────────────────────────────────────────────────────

def _compute_metrics(history: list[dict]) -> dict[str, Any]:
    if not history:
        return {}
    values = [e["total_value_eur"] for e in history]
    initial = history[0].get("total_value_eur", values[0])
    final = values[-1]
    total_return = (final - initial) / initial * 100 if initial else 0
    n = len(values)

    daily_rets = [(values[i] - values[i - 1]) / values[i - 1] * 100
                  for i in range(1, len(values)) if values[i - 1] > 0]
    n_days = len(daily_rets)
    avg_dr = sum(daily_rets) / n_days if n_days else 0
    daily_vol = math.sqrt(sum((r - avg_dr) ** 2 for r in daily_rets) / n_days) if n_days else 0
    ann_return = total_return / n * 252 if n else 0
    ann_vol = daily_vol * math.sqrt(252)
    sharpe = ann_return / ann_vol if ann_vol else 0

    peak, max_dd = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak * 100)
    calmar = ann_return / max_dd if max_dd else 0

    gains = [r for r in daily_rets if r > 0]
    losses = [r for r in daily_rets if r < 0]
    win_rate = len(gains) / n_days * 100 if n_days else 0
    profit_factor = abs(sum(gains) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    return {
        "total_return": total_return,
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "values": values,
        "n_entries": n,
    }


# ── Chart builders ────────────────────────────────────────────────────────────

def _chart_equity_comparison(portfolios: dict) -> str:
    fig, ax = plt.subplots(figsize=(11, 3.2))
    has_data = False
    for name in STRATEGIES:
        p = portfolios.get(name, {})
        history = p.get("iterations_log", [])
        if not history:
            continue
        ts, vals = [], []
        for e in history:
            try:
                ts.append(_parse_ts(e["timestamp"]))
                vals.append(e["total_value_eur"])
            except (KeyError, ValueError):
                pass
        if ts:
            ax.plot(ts, vals, color=STRATEGY_COLORS.get(name, "#94a3b8"),
                    linewidth=2, label=STRATEGY_LABELS.get(name, name))
            has_data = True

    if not has_data:
        ax.text(0.5, 0.5, "In attesa della prima sessione di trading",
                ha="center", va="center", transform=ax.transAxes, color="#64748b", fontsize=12)
    else:
        ax.axhline(INITIAL_CAPITAL, color="#475569", linewidth=1, linestyle="--",
                   label=f"Capitale iniziale {INITIAL_CAPITAL:.0f}€")
        legend = ax.legend(loc="upper left", fontsize=9, fancybox=False,
                           framealpha=0.3, labelcolor="#e2e8f0")
        legend.get_frame().set_facecolor("#1e293b")
        legend.get_frame().set_edgecolor("#334155")

    ax.set_title("Performance Comparison — Tutte le strategie", color="#f8fafc", fontweight="bold")
    ax.set_ylabel("EUR", color="#94a3b8")
    if has_data:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    fig.patch.set_facecolor("#0f172a")
    _dark_ax(ax)
    return _fig_to_b64(fig)


def _chart_equity_cash(history: list, strategy_name: str, color: str) -> str:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3))
    values = [e["total_value_eur"] for e in history]
    cash_vals = [e["current_cash"] for e in history]
    ts = [_parse_ts(e["timestamp"]) for e in history]
    fmt = mdates.DateFormatter("%d/%m")

    if ts:
        ax1.plot(ts, values, color=color, linewidth=2)
        ax1.fill_between(ts, values, alpha=0.1, color=color)
        ax1.xaxis.set_major_formatter(fmt)
    ax1.set_title(f"Equity — {STRATEGY_LABELS.get(strategy_name, strategy_name)}",
                  color="#f8fafc", fontweight="bold", fontsize=10)
    ax1.set_ylabel("EUR", color="#94a3b8")
    _dark_ax(ax1)

    if ts:
        ax2.plot(ts, cash_vals, color="#64748b", linewidth=2)
        ax2.fill_between(ts, cash_vals, alpha=0.1, color="#64748b")
        ax2.xaxis.set_major_formatter(fmt)
    ax2.set_title("Cash", color="#f8fafc", fontweight="bold", fontsize=10)
    ax2.set_ylabel("EUR", color="#94a3b8")
    _dark_ax(ax2)

    fig.patch.set_facecolor("#0f172a")
    fig.tight_layout()
    return _fig_to_b64(fig)


def _chart_allocation_sector(positions: dict, pos_equity: dict) -> str:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.2))

    if positions:
        labels = sorted(positions.keys())
        sizes = [pos_equity.get(t, 1) for t in labels]
        colors_al = plt.cm.Set3(range(len(labels)))
        wedges, _, autotexts = ax1.pie(
            sizes, labels=None, autopct="%1.0f%%",
            startangle=90, colors=colors_al, pctdistance=0.7,
        )
        for at in autotexts:
            at.set_fontsize(7)
            at.set_color("#e2e8f0")
        ax1.legend(wedges, labels, loc="lower center", fontsize=6,
                   ncol=min(3, len(labels)), bbox_to_anchor=(0.5, -0.25),
                   labelcolor="#e2e8f0", facecolor="#1e293b", edgecolor="#334155")
    ax1.set_facecolor("#1e293b")  # Fix: dark theme for pie
    ax1.set_title("Allocation (EUR)", color="#f8fafc", fontweight="bold", fontsize=10)

    sector_values: dict[str, float] = {}
    for t, eq in pos_equity.items():
        sec = UNIVERSE.get(t, {}).get("sector", "Other")
        sector_values[sec] = sector_values.get(sec, 0) + eq
    if sector_values:
        sec_labels = list(sector_values.keys())
        sec_sizes = list(sector_values.values())
        bars = ax2.barh(sec_labels, sec_sizes,
                        color=plt.cm.Set2(range(len(sec_labels))), height=0.6)
        for bar, v in zip(bars, sec_sizes):
            ax2.text(v + 2, bar.get_y() + bar.get_height() / 2,
                     f"{v:.0f}€", va="center", fontsize=8, color="#94a3b8")
    ax2.set_title("Sector Exposure (EUR)", color="#f8fafc", fontweight="bold", fontsize=10)
    _dark_ax(ax2)

    fig.patch.set_facecolor("#0f172a")
    fig.tight_layout()
    return _fig_to_b64(fig)


def _chart_drawdown_pnl(history: list, positions: dict, pos_equity: dict) -> str:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.2))
    values = [e["total_value_eur"] for e in history]
    ts = [_parse_ts(e["timestamp"]) for e in history]

    if ts and values:
        peak, dd_vals = values[0], []
        for v in values:
            peak = max(peak, v)
            dd_vals.append((v - peak) / peak * 100)
        ax1.fill_between(ts, dd_vals, 0, color="#ef4444", alpha=0.7)
        ax1.plot(ts, dd_vals, color="#ef4444", linewidth=1)
        ax1.axhline(0, color="#94a3b8", linewidth=0.5)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax1.set_title("Drawdown", color="#f8fafc", fontweight="bold", fontsize=10)
    ax1.set_ylabel("%", color="#94a3b8")
    _dark_ax(ax1)

    pnl_tickers, pnl_vals, pnl_cols = [], [], []
    for t in sorted(pos_equity):
        eq = pos_equity[t]
        cost = positions[t]["shares"] * positions[t]["avg_price"]
        pnl = eq - cost
        pnl_tickers.append(t)
        pnl_vals.append(pnl)
        pnl_cols.append("#22c55e" if pnl >= 0 else "#ef4444")
    if pnl_tickers:
        bars = ax2.barh(pnl_tickers, pnl_vals, color=pnl_cols, height=0.6)
        for bar, val in zip(bars, pnl_vals):
            if abs(val) > 1:
                ax2.text(val + (2 if val >= 0 else -2),
                         bar.get_y() + bar.get_height() / 2,
                         f"{val:+.1f}€", va="center", fontsize=7, color="#94a3b8")
    ax2.set_title("P&L Live per posizione", color="#f8fafc", fontweight="bold", fontsize=10)
    ax2.axvline(0, color="#94a3b8", linewidth=0.5)
    _dark_ax(ax2)

    fig.patch.set_facecolor("#0f172a")
    fig.tight_layout()
    return _fig_to_b64(fig)


# ── HTML builder ──────────────────────────────────────────────────────────────

def build_live_html(portfolios: dict[str, Any], live_prices: dict[str, float]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Strategy cards ──
    cards_html = '<div class="strategy-cards">'
    for name in STRATEGIES:
        p = portfolios.get(name, {})
        cash = p["metadata"].get("current_cash", 0)
        initial = p["metadata"].get("initial_capital", INITIAL_CAPITAL)
        pos = p.get("current_positions", {})
        equity = sum(
            pos[t]["shares"] * _to_eur(live_prices.get(t, pos[t]["avg_price"]),
                                        UNIVERSE.get(t, {}).get("currency", "EUR"))
            for t in pos
        )
        total = cash + equity
        ret_pct = (total - initial) / initial * 100 if initial else 0
        badge_cls = "badge-pos" if ret_pct >= 0 else "badge-neg"
        arrow = "▲" if ret_pct >= 0 else "▼"
        color = STRATEGY_COLORS.get(name, "#94a3b8")
        cards_html += f"""
        <div class="strategy-card" style="border-top: 3px solid {color};">
          <div class="strat-name">{STRATEGY_LABELS.get(name, name)}</div>
          <div class="strat-value">{total:,.2f} €</div>
          <span class="strat-return {badge_cls}">{arrow} {ret_pct:+.2f}%</span>
          <div class="strat-daily">{len(pos)} posizioni · {cash:.0f}€ cash</div>
        </div>"""
    cards_html += "</div>"

    # ── Comparison chart ──
    comparison_chart = _chart_equity_comparison(portfolios)

    # ── Per-strategy tabs ──
    tab_buttons = ""
    tab_panels = ""
    for i, name in enumerate(STRATEGIES):
        p = portfolios.get(name, {})
        history = p.get("iterations_log", [])
        positions = p.get("current_positions", {})
        metadata = p.get("metadata", {})
        cash = metadata.get("current_cash", 0)
        color = STRATEGY_COLORS.get(name, "#94a3b8")
        label = STRATEGY_LABELS.get(name, name)
        active = "active" if i == 0 else ""

        tab_buttons += f'<button class="tab-btn {active}" onclick="showTab(\'{name}\')" id="btn-{name}">{label}</button>'

        # Compute portfolio value
        pos_equity: dict[str, float] = {}
        total_eur = cash
        for ticker, pos_data in positions.items():
            cur_local = live_prices.get(ticker, pos_data["avg_price"])
            ccy = UNIVERSE.get(ticker, {}).get("currency", "EUR")
            cur_eur = _to_eur(cur_local, ccy)
            eq = pos_data["shares"] * cur_eur
            pos_equity[ticker] = eq
            total_eur += eq

        initial = metadata.get("initial_capital", INITIAL_CAPITAL)
        ret_pct = (total_eur - initial) / initial * 100 if initial else 0

        m = _compute_metrics(history)

        # Metric cards
        metrics_html = f"""
        <div class="metric-grid">
          <div class="card"><div class="val">{total_eur:,.2f}€</div><div class="lbl">Valore Live</div></div>
          <div class="card"><div class="val" style="color:{'#22c55e' if ret_pct>=0 else '#ef4444'}">{ret_pct:+.2f}%</div><div class="lbl">Total Return</div></div>
          <div class="card"><div class="val">{m.get('sharpe', 0):.2f}</div><div class="lbl">Sharpe</div></div>
          <div class="card"><div class="val" style="color:#ef4444">{m.get('max_drawdown', 0):.2f}%</div><div class="lbl">Max DD</div></div>
          <div class="card"><div class="val">{m.get('ann_vol', 0):.2f}%</div><div class="lbl">Ann. Vol</div></div>
          <div class="card"><div class="val">{m.get('win_rate', 0):.1f}%</div><div class="lbl">Win Rate</div></div>
          <div class="card"><div class="val">{cash:,.2f}€</div><div class="lbl">Cash</div></div>
          <div class="card"><div class="val">{len(positions)}</div><div class="lbl">Posizioni</div></div>
        </div>"""

        # Charts (only if history)
        charts_html = ""
        if history:
            charts_html += f'<img src="{_chart_equity_cash(history, name, color)}" style="width:100%;border-radius:8px;margin-bottom:12px;" alt="Equity">'
        if positions:
            charts_html += f'<img src="{_chart_allocation_sector(positions, pos_equity)}" style="width:100%;border-radius:8px;margin-bottom:12px;" alt="Allocation">'
            if history:
                charts_html += f'<img src="{_chart_drawdown_pnl(history, positions, pos_equity)}" style="width:100%;border-radius:8px;margin-bottom:12px;" alt="Drawdown">'

        # Positions table
        pos_rows = ""
        for ticker in sorted(positions):
            pd_data = positions[ticker]
            info = UNIVERSE.get(ticker, {})
            ccy = info.get("currency", "EUR")
            cur_local = live_prices.get(ticker, pd_data["avg_price"])
            cur_eur = _to_eur(cur_local, ccy)
            eq = pd_data["shares"] * cur_eur
            cost = pd_data["shares"] * pd_data["avg_price"]
            pnl_e = eq - cost
            pnl_p = (cur_eur / pd_data["avg_price"] - 1) * 100 if pd_data["avg_price"] > 0 else 0
            cls = "neg" if pnl_e < 0 else "pos"
            pos_rows += (
                f"<tr><td><strong>{ticker}</strong></td><td>{info.get('exchange','')}</td>"
                f"<td>{info.get('sector','')}</td><td>{ccy}</td><td>{pd_data['shares']}</td>"
                f"<td>{pd_data['avg_price']:.2f}</td><td>{cur_eur:.2f}</td><td>{eq:.2f}</td>"
                f"<td class='{cls}'>{pnl_e:+.2f}</td><td class='{cls}'>{pnl_p:+.2f}%</td></tr>"
            )

        # Transactions table
        tx_rows = ""
        for e in reversed(history):
            for tx in e.get("transactions", []):
                a = tx["action"]
                cls = "tx-buy" if a == "BUY" else "tx-sell"
                ts_str = e.get("timestamp", "")[:16].replace("T", " ")
                total_tx = tx.get("total_cost_eur", tx.get("total_proceeds_eur", 0))
                tx_rows += (
                    f"<tr><td>{ts_str}</td><td class='{cls}'>{a}</td>"
                    f"<td><strong>{tx['ticker']}</strong></td><td>{tx['shares']}</td>"
                    f"<td>{tx.get('price_eur', 0):.2f}</td><td>{total_tx:.2f}</td></tr>"
                )

        if not tx_rows:
            tx_rows = '<tr><td colspan="6" style="color:#64748b;text-align:center">Nessuna transazione ancora</td></tr>'

        tab_panels += f"""
        <div id="panel-{name}" class="tab-panel {active}">
          {metrics_html}
          <div class="charts">{charts_html if (history or positions) else '<p style="color:#64748b;padding:16px">In attesa della prima sessione di trading.</p>'}</div>
          <div class="section-title">Posizioni ({len(positions)})</div>
          <div style="overflow-x:auto">
            <table><thead><tr>
              <th>Ticker</th><th>Exc</th><th>Sector</th><th>CCY</th><th>Shares</th>
              <th>Avg€</th><th>Live€</th><th>Equity€</th><th>P&L€</th><th>P&L%</th>
            </tr></thead><tbody>{pos_rows if pos_rows else '<tr><td colspan="10" style="color:#64748b;text-align:center">Nessuna posizione aperta</td></tr>'}</tbody></table>
          </div>
          <div class="section-title" style="margin-top:20px">Transazioni</div>
          <div style="overflow-x:auto;max-height:300px;overflow-y:auto">
            <table><thead><tr><th>Data</th><th>Azione</th><th>Ticker</th><th>Shares</th><th>Prezzo€</th><th>Totale€</th></tr></thead>
            <tbody>{tx_rows}</tbody></table>
          </div>
        </div>"""

    pos_data_json = json.dumps(
        [
            {
                "ticker": t,
                "shares": p["shares"],
                "avg_price": p["avg_price"],
                "currency": UNIVERSE.get(t, {}).get("currency", "EUR"),
                "exchange": UNIVERSE.get(t, {}).get("exchange", ""),
                "sector": UNIVERSE.get(t, {}).get("sector", ""),
                "initial_price": live_prices.get(t, p["avg_price"]),
                "initial_equity": pos_equity.get(t, 0),
            }
            for t, p in sorted(positions.items())
        ]
    )

    initial_total = round(total_eur, 2)
    initial_capital = metadata.get("initial_capital", 3000)
    initial_cash = round(cash, 2)

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="60">
<title>AI Hedge Fund — Live Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0}}
a{{color:#38bdf8;text-decoration:none}}
.header{{background:linear-gradient(135deg,#1e293b,#0f172a);padding:20px 32px;border-bottom:1px solid #334155;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}}
.header h1{{font-size:20px;font-weight:700;color:#f8fafc}}
.header p{{color:#94a3b8;font-size:12px;margin-top:4px}}
.badge-live{{background:#22c55e;color:#0f172a;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-left:8px}}
.container{{max-width:1280px;margin:0 auto;padding:20px 24px}}
.section-title{{font-size:13px;font-weight:700;margin:20px 0 10px;color:#f1f5f9;text-transform:uppercase;letter-spacing:0.5px;border-left:3px solid #334155;padding-left:8px}}
.strategy-cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}}
.strategy-card{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:16px}}
.strat-name{{font-size:10px;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;margin-bottom:6px}}
.strat-value{{font-size:22px;font-weight:700;color:#f8fafc}}
.strat-return{{font-size:13px;font-weight:600;margin-top:4px;display:inline-block;padding:2px 7px;border-radius:4px}}
.badge-pos{{background:rgba(34,197,94,.15);color:#22c55e}}
.badge-neg{{background:rgba(239,68,68,.15);color:#ef4444}}
.strat-daily{{font-size:11px;margin-top:6px;color:#64748b}}
.chart-wrap{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:14px;margin-bottom:20px}}
.chart-wrap img{{width:100%;border-radius:6px}}
.metric-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:16px}}
.card{{background:#0f172a;border:1px solid #334155;border-radius:8px;padding:14px;text-align:center}}
.card .val{{font-size:18px;font-weight:700;color:#22c55e}}
.card .lbl{{font-size:10px;color:#94a3b8;margin-top:3px;text-transform:uppercase;letter-spacing:.5px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#1e293b;color:#64748b;text-align:left;padding:8px 10px;font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:.5px;border-bottom:1px solid #334155;position:sticky;top:0}}
td{{padding:7px 10px;border-bottom:1px solid #1a2332}}
tr:hover td{{background:#1e293b}}
.pos{{color:#22c55e}}.neg{{color:#ef4444}}
.tx-buy{{color:#22c55e;font-weight:600}}.tx-sell{{color:#ef4444;font-weight:600}}
.tabs-wrap{{background:#1e293b;border:1px solid #334155;border-radius:10px;overflow:hidden}}
.tab-buttons{{display:flex;background:#0f172a;border-bottom:1px solid #334155;flex-wrap:wrap}}
.tab-btn{{background:transparent;border:none;color:#64748b;padding:11px 18px;cursor:pointer;font-size:13px;font-weight:500;transition:all .15s;border-bottom:2px solid transparent}}
.tab-btn:hover{{color:#e2e8f0;background:#1e293b}}
.tab-btn.active{{color:#f8fafc;border-bottom-color:#38bdf8}}
.tab-panel{{display:none;padding:18px}}
.tab-panel.active{{display:block}}
.footer{{text-align:center;padding:20px;color:#475569;font-size:11px;border-top:1px solid #1e293b;margin-top:20px}}
@media(max-width:768px){{.strategy-cards{{grid-template-columns:repeat(2,1fr)}}}}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>AI Hedge Fund <span class="badge-live">LIVE</span></h1>
    <p>{now} · 4 strategie · 20 ticker · NASDAQ · NYSE · FTSE · BIT · Prezzi yfinance · refresh 60s</p>
  </div>
</div>

<div class="container">

  <div class="section-title">Riepilogo Portafogli</div>
  {cards_html}

  <div class="section-title">Performance Comparison</div>
  <div class="chart-wrap">
    <img src="{comparison_chart}" alt="Performance Comparison">
  </div>

  <div class="section-title">Dettaglio per Strategia</div>
  <div class="tabs-wrap">
    <div class="tab-buttons">{tab_buttons}</div>
    {tab_panels}
  </div>

</div>

<div class="footer">
  <a href="/api/prices">API Prezzi</a> &middot;
  <a href="/api/portfolios">API Portfolios</a> &middot;
  <a href="/health">Health</a> &middot;
  Prezzi aggiornati ogni 60s &middot; {now}
</div>

<script>
function showTab(name) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  document.getElementById('btn-' + name).classList.add('active');
}}
</script>
</body>
</html>"""
