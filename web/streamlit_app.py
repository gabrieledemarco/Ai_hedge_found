"""
AI Hedge Fund — Live Monitor (Streamlit Cloud)

Real-time dashboard: reads portfolio JSONs from GitHub raw URLs,
fetches live prices via yfinance, auto-refreshes every 60s.

Deploy: share.streamlit.io → repo gabrieledemarco/Ai_hedge_found → web/streamlit_app.py
"""

import time
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="AI Hedge Fund — Live Monitor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Constants ────────────────────────────────────────────────────────────────

GITHUB_RAW = (
    "https://raw.githubusercontent.com/gabrieledemarco/Ai_hedge_found/main"
)
STRATEGIES = ["equal_weight", "momentum", "fundamental", "sentiment"]
STRATEGY_LABELS = {
    "equal_weight": "Equal Weight",
    "momentum": "Momentum",
    "fundamental": "Fundamental",
    "sentiment": "Sentiment",
}
STRATEGY_COLORS = {
    "equal_weight": "#22c55e",
    "momentum": "#3b82f6",
    "fundamental": "#f59e0b",
    "sentiment": "#a855f7",
}
UNIVERSE = {
    "AAPL":    {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "MSFT":    {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "GOOGL":   {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "AMZN":    {"exchange": "NASDAQ", "currency": "USD", "sector": "Consumer"},
    "TSLA":    {"exchange": "NASDAQ", "currency": "USD", "sector": "Auto"},
    "JPM":     {"exchange": "NYSE",   "currency": "USD", "sector": "Financial"},
    "NVDA":    {"exchange": "NASDAQ", "currency": "USD", "sector": "Tech"},
    "JNJ":     {"exchange": "NYSE",   "currency": "USD", "sector": "Healthcare"},
    "V":       {"exchange": "NYSE",   "currency": "USD", "sector": "Financial"},
    "KO":      {"exchange": "NYSE",   "currency": "USD", "sector": "Consumer"},
    "ULVR.L":  {"exchange": "FTSE",   "currency": "GBP", "sector": "Consumer"},
    "HSBA.L":  {"exchange": "FTSE",   "currency": "GBP", "sector": "Financial"},
    "BP.L":    {"exchange": "FTSE",   "currency": "GBP", "sector": "Energy"},
    "GSK.L":   {"exchange": "FTSE",   "currency": "GBP", "sector": "Healthcare"},
    "RIO.L":   {"exchange": "FTSE",   "currency": "GBP", "sector": "Materials"},
    "ENI.MI":  {"exchange": "BIT",    "currency": "EUR", "sector": "Energy"},
    "ISP.MI":  {"exchange": "BIT",    "currency": "EUR", "sector": "Financial"},
    "ENEL.MI": {"exchange": "BIT",    "currency": "EUR", "sector": "Utilities"},
    "LDO.MI":  {"exchange": "BIT",    "currency": "EUR", "sector": "Aerospace"},
    "MONC.MI": {"exchange": "BIT",    "currency": "EUR", "sector": "Consumer"},
}
INITIAL_CAPITAL = 3000.0

# ── Data loading ─────────────────────────────────────────────────────────────


@st.cache_data(ttl=300)
def load_portfolio(strategy: str) -> dict:
    url = f"{GITHUB_RAW}/data/portfolios/{strategy}.json"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {
            "strategy": strategy,
            "metadata": {"initial_capital": INITIAL_CAPITAL, "current_cash": INITIAL_CAPITAL},
            "current_positions": {},
            "iterations_log": [],
        }


@st.cache_data(ttl=300)
def load_signals() -> dict:
    url = f"{GITHUB_RAW}/data/signals.json"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


@st.cache_data(ttl=60)
def fetch_live_prices(tickers: tuple) -> dict[str, float]:
    """Returns EUR prices for all tickers. 60s cache."""
    fx = {"USD": 0.92, "GBP": 1.17, "EUR": 1.0}
    prices: dict[str, float] = {}
    try:
        raw = yf.download(
            list(tickers),
            period="2d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        close = raw["Close"] if "Close" in raw.columns else pd.DataFrame()
        for t in tickers:
            col = t if t in close.columns else None
            if col and not close[col].dropna().empty:
                local = float(close[col].dropna().iloc[-1])
                ccy = UNIVERSE.get(t, {}).get("currency", "EUR")
                prices[t] = round(local * fx.get(ccy, 1.0), 4)
    except Exception:
        pass
    # Fallback: fetch one by one for missing tickers
    missing = [t for t in tickers if t not in prices]
    for t in missing:
        try:
            hist = yf.Ticker(t).history(period="2d")
            if not hist.empty:
                local = float(hist["Close"].dropna().iloc[-1])
                ccy = UNIVERSE.get(t, {}).get("currency", "EUR")
                prices[t] = round(local * fx.get(ccy, 1.0), 4)
        except Exception:
            prices[t] = 0.0
    return prices


# ── Computation helpers ───────────────────────────────────────────────────────


def portfolio_value(portfolio: dict, live_prices: dict) -> tuple[float, float, float]:
    """Returns (total_eur, pnl_eur, pnl_pct)."""
    cash = portfolio["metadata"].get("current_cash", 0.0)
    equity = sum(
        pos["shares"] * live_prices.get(t, pos.get("avg_price", 0))
        for t, pos in portfolio.get("current_positions", {}).items()
    )
    total = cash + equity
    initial = portfolio["metadata"].get("initial_capital", INITIAL_CAPITAL)
    pnl = total - initial
    pnl_pct = pnl / initial * 100 if initial > 0 else 0.0
    return total, pnl, pnl_pct


def daily_change(portfolio: dict, live_prices: dict) -> float:
    """P&L vs yesterday's closing value from iterations_log."""
    logs = portfolio.get("iterations_log", [])
    if len(logs) < 2:
        return 0.0
    yesterday = logs[-2].get("total_value_eur", 0.0)
    today_total, _, _ = portfolio_value(portfolio, live_prices)
    return today_total - yesterday if yesterday > 0 else 0.0


# ── CSS ──────────────────────────────────────────────────────────────────────

DARK_CSS = """
<style>
[data-testid="stAppViewContainer"] { background: #0f172a; }
[data-testid="stHeader"] { background: transparent; }
section[data-testid="stSidebar"] { background: #1e293b; }
[data-testid="stMetricValue"] { font-size: 1.6rem !important; color: #f1f5f9; }
[data-testid="stMetricLabel"] { color: #94a3b8; font-size: 0.8rem; }
[data-testid="stMetricDelta"] { font-size: 0.9rem; }
div[data-testid="stHorizontalBlock"] > div { padding: 8px; }
.stTabs [data-baseweb="tab"] { color: #94a3b8; }
.stTabs [aria-selected="true"] { color: #f1f5f9 !important; }
h2, h3 { color: #f1f5f9; }
.stDataFrame { border-radius: 8px; }
</style>
"""


# ── Main app ─────────────────────────────────────────────────────────────────


def main() -> None:
    st.markdown(DARK_CSS, unsafe_allow_html=True)

    # Header
    col_h1, col_h2 = st.columns([4, 1])
    with col_h1:
        st.markdown("## 📈 AI Hedge Fund — Live Monitor")
        st.caption(
            "4 strategie in paper trading · Aggiornamento prezzi ogni 60s · "
            "Portfolio aggiornato 3x/giorno da GitHub Actions"
        )
    with col_h2:
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        st.metric("Ora", now_str)

    st.divider()

    # Load data
    tickers_tuple = tuple(UNIVERSE.keys())
    with st.spinner("Caricamento prezzi live..."):
        live_prices = fetch_live_prices(tickers_tuple)
        portfolios = {s: load_portfolio(s) for s in STRATEGIES}
        signals = load_signals()

    # ── Section 1: Strategy Cards ────────────────────────────────────────────
    st.markdown("### Performance Portafogli")
    cols = st.columns(4)
    for i, strat in enumerate(STRATEGIES):
        p = portfolios[strat]
        total, pnl, pnl_pct = portfolio_value(p, live_prices)
        delta_today = daily_change(p, live_prices)
        delta_str = f"{delta_today:+.2f}€ oggi  |  {pnl:+.2f}€ totale ({pnl_pct:+.2f}%)"
        with cols[i]:
            st.metric(
                label=STRATEGY_LABELS[strat],
                value=f"{total:,.2f} €",
                delta=delta_str,
            )

    st.divider()

    # ── Section 2: Equity Comparison Chart ───────────────────────────────────
    st.markdown("### Equity Curves — Confronto Strategie")

    fig = go.Figure()
    has_data = False
    for strat in STRATEGIES:
        logs = portfolios[strat].get("iterations_log", [])
        if not logs:
            continue
        dates, values = [], []
        for entry in logs:
            try:
                dates.append(entry["timestamp"])
                values.append(entry["total_value_eur"])
            except KeyError:
                pass
        if dates:
            fig.add_trace(go.Scatter(
                x=dates, y=values,
                mode="lines",
                name=STRATEGY_LABELS[strat],
                line=dict(color=STRATEGY_COLORS[strat], width=2),
                hovertemplate=(
                    "<b>" + STRATEGY_LABELS[strat] + "</b><br>"
                    "%{x|%d/%m %H:%M}<br>"
                    "Valore: %{y:.2f}€<extra></extra>"
                ),
            ))
            has_data = True

    fig.add_hline(
        y=INITIAL_CAPITAL,
        line_dash="dot",
        line_color="#475569",
        annotation_text="Capitale iniziale 3.000€",
        annotation_font_color="#64748b",
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f172a",
        plot_bgcolor="#1e293b",
        legend=dict(
            bgcolor="#1e293b",
            bordercolor="#334155",
            borderwidth=1,
            font=dict(color="#e2e8f0"),
        ),
        yaxis=dict(title="Valore (€)", gridcolor="#1e293b"),
        xaxis=dict(gridcolor="#1e293b"),
        height=380,
        margin=dict(l=0, r=0, t=10, b=0),
        hovermode="x unified",
    )

    if not has_data:
        fig.add_annotation(
            text="Nessun dato storico ancora — in attesa della prima sessione di trading",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(color="#64748b", size=14),
        )

    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Section 3: Live Positions Tabs ───────────────────────────────────────
    st.markdown("### Posizioni Correnti — P&L Live")
    tab_labels = [STRATEGY_LABELS[s] for s in STRATEGIES]
    tabs = st.tabs(tab_labels)

    for i, strat in enumerate(STRATEGIES):
        with tabs[i]:
            p = portfolios[strat]
            positions = p.get("current_positions", {})
            cash = p["metadata"].get("current_cash", 0.0)
            total, pnl, pnl_pct = portfolio_value(p, live_prices)

            c1, c2, c3 = st.columns(3)
            c1.metric("Valore Totale", f"{total:,.2f} €", f"{pnl:+.2f}€")
            c2.metric("Cash", f"{cash:,.2f} €")
            c3.metric("Posizioni Aperte", len(positions))

            if not positions:
                st.info("Nessuna posizione aperta. Capitale tutto in cash.")
                continue

            rows = []
            for ticker in sorted(positions):
                pos = positions[ticker]
                live_eur = live_prices.get(ticker, pos["avg_price"])
                equity = pos["shares"] * live_eur
                cost = pos["shares"] * pos["avg_price"]
                pnl_e = equity - cost
                pnl_p = pnl_e / cost * 100 if cost > 0 else 0.0
                rows.append({
                    "Ticker": ticker,
                    "Settore": UNIVERSE.get(ticker, {}).get("sector", "—"),
                    "Exchange": UNIVERSE.get(ticker, {}).get("exchange", "—"),
                    "Shares": pos["shares"],
                    "Avg (€)": round(pos["avg_price"], 2),
                    "Live (€)": round(live_eur, 2),
                    "Equity (€)": round(equity, 2),
                    "P&L €": round(pnl_e, 2),
                    "P&L %": round(pnl_p, 2),
                })

            df = pd.DataFrame(rows)

            def _color_pnl(v: float) -> str:
                return "color: #22c55e" if v >= 0 else "color: #ef4444"

            styled = df.style.map(_color_pnl, subset=["P&L €", "P&L %"])
            st.dataframe(styled, use_container_width=True, hide_index=True)

    st.divider()

    # ── Section 4: Stock Screener ─────────────────────────────────────────────
    st.markdown("### Stock Screener — Score Composito")
    st.caption(
        "Composite = 35% Sentiment + 35% F-Score + 30% Momentum 3m · "
        "Scores normalizzati 0–1 sull'universo"
    )

    sentiment_data = signals.get("sentiment", {})
    fundamental_data = signals.get("fundamentals", {})
    momentum_data = signals.get("momentum", {})

    def _normalize(vals: list[float]) -> list[float]:
        mn, mx = min(vals, default=0), max(vals, default=1)
        if mx == mn:
            return [0.5] * len(vals)
        return [(v - mn) / (mx - mn) for v in vals]

    tickers = list(UNIVERSE.keys())
    raw_mom = [momentum_data.get(t, {}).get("return_3m", 0.0) for t in tickers]
    raw_fs  = [fundamental_data.get(t, {}).get("f_score", 0.5) for t in tickers]
    raw_sent = [sentiment_data.get(t, {}).get("score", 0.0) for t in tickers]

    norm_mom  = _normalize(raw_mom)
    norm_fs   = _normalize(raw_fs)
    norm_sent = _normalize([(s + 1) / 2 for s in raw_sent])

    screener_rows = []
    for idx, ticker in enumerate(tickers):
        composite = 0.30 * norm_mom[idx] + 0.35 * norm_fs[idx] + 0.35 * norm_sent[idx]
        sent_label = sentiment_data.get(ticker, {}).get("label", "N/D")
        screener_rows.append({
            "Ticker": ticker,
            "Exchange": UNIVERSE[ticker]["exchange"],
            "Settore": UNIVERSE[ticker]["sector"],
            "Prezzo (€)": round(live_prices.get(ticker, 0.0), 2),
            "Mom 3m %": round(raw_mom[idx] * 100, 1),
            "F-Score": round(raw_fs[idx], 2),
            "Sentiment": sent_label,
            "Composite ▼": round(composite, 3),
        })

    screener_df = (
        pd.DataFrame(screener_rows)
        .sort_values("Composite ▼", ascending=False)
        .reset_index(drop=True)
    )

    def _color_composite(v: float) -> str:
        if v >= 0.6:
            return "background-color: #052e16; color: #22c55e"
        if v >= 0.4:
            return "background-color: #1c1917; color: #f59e0b"
        return "background-color: #2d0a0a; color: #ef4444"

    styled_screener = (
        screener_df.style
        .map(_color_composite, subset=["Composite ▼"])
        .map(lambda v: "color: #22c55e" if v >= 0 else "color: #ef4444",
             subset=["Mom 3m %"])
    )
    st.dataframe(styled_screener, use_container_width=True, hide_index=True, height=580)

    signals_ts = signals.get("fundamentals_updated", "mai")
    if signals_ts != "mai":
        signals_ts = signals_ts[:16].replace("T", " ") + " UTC"
    st.caption(f"Signals aggiornati: {signals_ts} · Market Analysis workflow (05:30 UTC lun–ven)")

    st.divider()

    # ── Footer ────────────────────────────────────────────────────────────────
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        st.caption(
            "GitHub: [gabrieledemarco/Ai_hedge_found]"
            "(https://github.com/gabrieledemarco/Ai_hedge_found)"
        )
    with fc2:
        st.caption(
            "GitHub Pages (snapshot statico): "
            "[Dashboard](https://gabrieledemarco.github.io/Ai_hedge_found/)"
        )
    with fc3:
        st.caption("Auto-refresh ogni 60s · Powered by yfinance + FinBERT")

    # Auto-refresh
    time.sleep(60)
    st.rerun()


if __name__ == "__main__":
    main()
