import os
import json
import math
from datetime import datetime, timezone
from typing import Any

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


def _calc_max_drawdown(values: list[float]) -> tuple[float, int, int]:
    peak = values[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_end = 0
    max_dd_start = 0
    for i, v in enumerate(values):
        if v > peak:
            peak = v
            peak_idx = i
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd
            max_dd_start = peak_idx
            max_dd_end = i
    return max_dd, max_dd_start, max_dd_end


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
    max_dd, dd_start, dd_end = _calc_max_drawdown(values)
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
        "dd_start_idx": dd_start,
        "dd_end_idx": dd_end,
        "daily_rets": daily_rets,
        "values": values,
    }


def build_html(portfolio: dict) -> str:
    _load_universe()
    history = portfolio.get("iterations_log", [])
    metrics = _compute_metrics(history)
    positions = portfolio.get("current_positions", {})
    metadata = portfolio.get("metadata", {})
    cash = metadata.get("current_cash", 0)
    total_eur = metrics.get("final", cash)

    timestamps_json = json.dumps([e["timestamp"] for e in history]) if history else "[]"
    values_json = (
        json.dumps([round(e["total_value_eur"], 2) for e in history])
        if history
        else "[]"
    )
    cash_history_json = (
        json.dumps([round(e["current_cash"], 2) for e in history]) if history else "[]"
    )

    m = metrics
    metric_cards = f"""
    <div class="metric-grid">
      <div class="card"><div class="val">{m.get("total_return", 0):.2f}%</div><div class="lbl">Total Return</div></div>
      <div class="card"><div class="val">{m.get("ann_return", 0):.2f}%</div><div class="lbl">Ann. Return (CAGR)</div></div>
      <div class="card"><div class="val">{m.get("ann_vol", 0):.2f}%</div><div class="lbl">Ann. Volatility</div></div>
      <div class="card"><div class="val">{m.get("sharpe", 0):.2f}</div><div class="lbl">Sharpe Ratio</div></div>
      <div class="card"><div class="val" style="color:#dc2626">{m.get("max_drawdown", 0):.2f}%</div><div class="lbl">Max Drawdown</div></div>
      <div class="card"><div class="val">{m.get("calmar", 0):.2f}</div><div class="lbl">Calmar Ratio</div></div>
      <div class="card"><div class="val">{m.get("win_rate", 0):.1f}%</div><div class="lbl">Win Rate</div></div>
      <div class="card"><div class="val">{m.get("profit_factor", 0):.2f}</div><div class="lbl">Profit Factor</div></div>
      <div class="card"><div class="val">{m.get("avg_win", 0):.2f}%</div><div class="lbl">Avg Winning Day</div></div>
      <div class="card"><div class="val" style="color:#dc2626">{m.get("avg_loss", 0):.2f}%</div><div class="lbl">Avg Losing Day</div></div>
    </div>"""

    pos_rows = ""
    pos_data_js_list = []
    for ticker in sorted(positions.keys()):
        p = positions[ticker]
        shares = p["shares"]
        avg_px = p["avg_price"]
        info = UNIVERSE.get(ticker, {})
        sector = info.get("sector", "")
        currency = info.get("currency", "")
        exchange = info.get("exchange", "")
        last_history_prices = {}
        if history:
            last_history_prices = history[-1].get("prices_used", {})
        cur_price = last_history_prices.get(ticker, avg_px)
        cur_price_eur = cur_price
        if currency == "USD":
            cur_price_eur = cur_price * 0.8663
        elif currency == "GBP":
            cur_price_eur = cur_price * 1.17
        eq = shares * cur_price_eur
        cost = shares * avg_px
        pnl_e = eq - cost
        pnl_p = ((cur_price_eur / avg_px) - 1) * 100 if avg_px > 0 else 0
        pnl_class = "neg" if pnl_e < 0 else "pos"
        pos_rows += f"""
        <tr>
          <td><strong>{ticker}</strong></td>
          <td>{exchange}</td>
          <td>{sector}</td>
          <td>{currency}</td>
          <td>{shares}</td>
          <td>{avg_px:.2f}</td>
          <td>{cur_price_eur:.2f}</td>
          <td>{eq:.2f}</td>
          <td class="{pnl_class}">{pnl_e:+.2f}</td>
          <td class="{pnl_class}">{pnl_p:+.2f}%</td>
        </tr>"""
        pos_data_js_list.append(
            {
                "ticker": ticker,
                "sector": sector,
                "exchange": exchange,
                "currency": currency,
                "shares": shares,
                "equity_eur": round(eq, 2),
                "pnl_eur": round(pnl_e, 2),
                "pnl_pct": round(pnl_p, 2),
            }
        )

    tx_rows = ""
    tx_data_js_list = []
    for e in reversed(history):
        for tx in e.get("transactions", []):
            a = tx["action"]
            cls = "tx-buy" if a == "BUY" else "tx-sell"
            tx_rows += f"""
            <tr>
              <td>{e.get("timestamp", "")[:16]}</td>
              <td class="{cls}">{a}</td>
              <td><strong>{tx["ticker"]}</strong></td>
              <td>{tx["shares"]}</td>
              <td>{tx.get("price_eur", 0):.2f}</td>
              <td>{tx.get("total_cost_eur", tx.get("total_proceeds_eur", 0)):.2f}</td>
            </tr>"""
            tx_data_js_list.append(
                {
                    "timestamp": e.get("timestamp", "")[:16],
                    "action": a,
                    "ticker": tx["ticker"],
                    "shares": tx["shares"],
                    "price_eur": tx.get("price_eur", 0),
                }
            )

    pos_data_json = json.dumps(pos_data_js_list)
    tx_data_json = json.dumps(tx_data_js_list)

    sector_data_json = "[]"
    if pos_data_js_list:
        sectors: dict[str, float] = {}
        for p in pos_data_js_list:
            s = p["sector"] or "Other"
            sectors[s] = sectors.get(s, 0) + p["equity_eur"]
        sector_data_json = json.dumps(
            [{"sector": k, "value": round(v, 2)} for k, v in sorted(sectors.items())]
        )

    asset_data_json = json.dumps(
        [{"ticker": p["ticker"], "value": p["equity_eur"]} for p in pos_data_js_list]
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Paper Trading Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0f172a; color:#e2e8f0; }}
.header {{ background:linear-gradient(135deg,#1e293b,#0f172a); padding:24px 32px; border-bottom:1px solid #334155; }}
.header h1 {{ font-size:24px; font-weight:700; color:#f8fafc; }}
.header p {{ color:#94a3b8; font-size:13px; margin-top:4px; }}
.container {{ max-width:1440px; margin:0 auto; padding:24px; }}
.metric-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; margin-bottom:24px; }}
.card {{ background:#1e293b; border:1px solid #334155; border-radius:10px; padding:16px; text-align:center; }}
.card .val {{ font-size:22px; font-weight:700; color:#22c55e; }}
.card .lbl {{ font-size:11px; color:#94a3b8; margin-top:4px; text-transform:uppercase; letter-spacing:0.5px; }}
.chart-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:24px; }}
.chart-full {{ grid-column:1/-1; }}
.chart-box {{ background:#1e293b; border:1px solid #334155; border-radius:10px; padding:12px; }}
.chart-box h3 {{ font-size:14px; font-weight:600; margin-bottom:8px; color:#cbd5e1; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#334155; color:#94a3b8; text-align:left; padding:8px 10px; font-weight:600; text-transform:uppercase; font-size:11px; letter-spacing:0.5px; }}
td {{ padding:8px 10px; border-bottom:1px solid #1e293b; }}
tr:hover td {{ background:#1e293b; }}
.pos {{ color:#22c55e; }}
.neg {{ color:#ef4444; }}
.tx-buy {{ color:#22c55e; font-weight:600; }}
.tx-sell {{ color:#ef4444; font-weight:600; }}
.section-title {{ font-size:16px; font-weight:600; margin:24px 0 12px; color:#f1f5f9; }}
@media(max-width:768px){{ .chart-grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="header">
  <h1>Paper Trading Dashboard</h1>
  <p>Aggiornato: {now} &middot; Capitale: {metadata.get("initial_capital", 0):.0f} EUR &middot; Multi-mercato: NASDAQ, NYSE, FTSE, BIT</p>
</div>
<div class="container">
  {metric_cards}

  <div class="chart-grid">
    <div class="chart-box chart-full"><h3>Equity Curve</h3><div id="chart-equity"></div></div>
    <div class="chart-box"><h3>Asset Allocation</h3><div id="chart-allocation"></div></div>
    <div class="chart-box"><h3>Sector Exposure</h3><div id="chart-sector"></div></div>
    <div class="chart-box"><h3>Drawdown</h3><div id="chart-drawdown"></div></div>
    <div class="chart-box"><h3>Daily Returns Distribution</h3><div id="chart-returns"></div></div>
    <div class="chart-box"><h3>PnL by Asset</h3><div id="chart-pnl"></div></div>
  </div>

  <div class="section-title">Posizioni Aperte ({len(positions)})</div>
  <div style="overflow-x:auto;">
  <table>
    <thead><tr><th>Ticker</th><th>Exchange</th><th>Sector</th><th>CCY</th><th>Shares</th><th>Avg Price</th><th>Cur Price</th><th>Equity</th><th>PnL</th><th>PnL%</th></tr></thead>
    <tbody>{pos_rows}</tbody>
  </table>
  </div>

  <div class="section-title">Transazioni ({len(tx_data_js_list)})</div>
  <div style="overflow-x:auto;max-height:400px;overflow-y:auto;">
  <table>
    <thead><tr><th>Date</th><th>Action</th><th>Ticker</th><th>Shares</th><th>Price</th><th>Total</th></tr></thead>
    <tbody>{tx_rows}</tbody>
  </table>
  </div>
</div>
<script>
const timestamps = {timestamps_json};
const values = {values_json};
const cashHist = {cash_history_json};
const posData = {pos_data_json};
const txData = {tx_data_json};
const sectorData = {sector_data_json};
const assetData = {asset_data_json};

Plotly.plot('chart-equity', [{{
  x: timestamps, y: values, type:'scatter', mode:'lines+markers',
  name:'Portfolio', line:{{color:'#22c55e',width:2}},
  marker:{{size:6,color:'#22c55e'}}
}},{{
  x: timestamps, y: cashHist, type:'scatter', mode:'lines',
  name:'Cash', line:{{color:'#3b82f6',width:1.5,dash:'dot'}}
}}], {{
  paper_bgcolor:'#1e293b', plot_bgcolor:'#1e293b',
  font:{{color:'#94a3b8',size:11}},
  xaxis:{{gridcolor:'#334155'}}, yaxis:{{gridcolor:'#334155',title:'EUR'}},
  margin:{{l:50,r:20,t:10,b:30}}, legend:{{orientation:'h',y:1.1}},
  hovermode:'x unified'
}});

if(assetData.length){{
  Plotly.plot('chart-allocation',[{{
    labels:assetData.map(d=>d.ticker), parents:assetData.map(()=>''), values:assetData.map(d=>d.value),
    type:'treemap', branchvalues:'total', textinfo:'label+percent entry',
    marker:{{colorscale:'Greens'}},
    hovertemplate:'%{{label}}<br>%{{value:.2f}} EUR<extra></extra>'
  }}], {{
    paper_bgcolor:'#1e293b', font:{{color:'#94a3b8',size:11}},
    margin:{{l:0,r:0,t:0,b:0}}
  }});
}}

if(sectorData.length){{
  Plotly.plot('chart-sector',[{{
    x:sectorData.map(d=>d.sector), y:sectorData.map(d=>d.value),
    type:'bar', marker:{{color:'#22c55e'}},
    hovertemplate:'%{{x}}<br>%{{y:.2f}} EUR<extra></extra>'
  }}], {{
    paper_bgcolor:'#1e293b', plot_bgcolor:'#1e293b',
    font:{{color:'#94a3b8',size:11}},
    xaxis:{{gridcolor:'#334155'}}, yaxis:{{gridcolor:'#334155',title:'EUR'}},
    margin:{{l:50,r:20,t:10,b:40}}
  }});
}}

const ddValues = values.map((v,i,a) => {{ if(i===0) return 0;
  const peak = Math.max(...a.slice(0,i+1));
  return (v-peak)/peak*100;
}});
Plotly.plot('chart-drawdown',[{{
  x:timestamps, y:ddValues, type:'scatter', mode:'lines',
  fill:'tozeroy', line:{{color:'#ef4444',width:1}},
  hovertemplate:'%{{y:.2f}}%<extra></extra>'
}}], {{
  paper_bgcolor:'#1e293b', plot_bgcolor:'#1e293b',
  font:{{color:'#94a3b8',size:11}},
  xaxis:{{gridcolor:'#334155'}}, yaxis:{{gridcolor:'#334155',title:'%',range:[-50,5]}},
  margin:{{l:50,r:20,t:10,b:30}}
}});

const dailyRets = {json.dumps(metrics.get("daily_rets", []))};
if(dailyRets.length){{
  Plotly.plot('chart-returns',[{{
    x:dailyRets, type:'histogram', nbinsx:20,
    marker:{{color:'#22c55e'}},
    hovertemplate:'%{{x:.2f}}%<extra></extra>'
  }}], {{
    paper_bgcolor:'#1e293b', plot_bgcolor:'#1e293b',
    font:{{color:'#94a3b8',size:11}},
    xaxis:{{gridcolor:'#334155',title:'Return %'}},
    yaxis:{{gridcolor:'#334155',title:'Freq'}},
    margin:{{l:50,r:20,t:10,b:40}}
  }});
}}

const pnlData = posData.filter(p=>p.shares>0);
if(pnlData.length){{
  const colors = pnlData.map(p => p.pnl_eur >= 0 ? '#22c55e' : '#ef4444');
  Plotly.plot('chart-pnl',[{{
    y:pnlData.map(p=>p.ticker), x:pnlData.map(p=>p.pnl_eur),
    type:'bar', orientation:'h', marker:{{color:colors}},
    hovertemplate:'%{{y}}<br>%{{x:.2f}} EUR<extra></extra>'
  }}], {{
    paper_bgcolor:'#1e293b', plot_bgcolor:'#1e293b',
    font:{{color:'#94a3b8',size:11}},
    xaxis:{{gridcolor:'#334155',title:'PnL EUR'}},
    yaxis:{{gridcolor:'#334155'}},
    margin:{{l:60,r:20,t:10,b:40}}
  }});
}}
</script>
</body>
</html>"""
