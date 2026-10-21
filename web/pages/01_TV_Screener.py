"""
TradingView Stock Screener — Streamlit multi-page app
Technical signal dashboard powered by TradingView's public scanner API.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components

# ── Path setup for script import ─────────────────────────────────────────────

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _ROOT)

from scripts.tradingview_screener import TV_TICKER_MAP, fetch_tv_screener, rating_label

# ── Universe metadata ─────────────────────────────────────────────────────────

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

GITHUB_RAW = "https://raw.githubusercontent.com/gabrieledemarco/Ai_hedge_found/main"

RATING_COLORS = {
    "Strong Buy":  ("#052e16", "#22c55e"),
    "Buy":         ("#0c1a33", "#60a5fa"),
    "Neutral":     ("#1c1917", "#94a3b8"),
    "Sell":        ("#2d1a00", "#f59e0b"),
    "Strong Sell": ("#2d0a0a", "#ef4444"),
    "N/D":         ("#1e293b", "#64748b"),
}

RATING_EMOJI = {
    "Strong Buy":  "🟢",
    "Buy":         "🔵",
    "Neutral":     "⚪",
    "Sell":        "🟡",
    "Strong Sell": "🔴",
    "N/D":         "⚫",
}

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TV Screener — AI Hedge Fund",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

DARK_CSS = """
<style>
[data-testid="stAppViewContainer"] { background: #0f172a; }
[data-testid="stHeader"]           { background: transparent; }
section[data-testid="stSidebar"]   { background: #1e293b; }
[data-testid="stMetricValue"]      { font-size: 1.5rem !important; color: #f1f5f9; }
[data-testid="stMetricLabel"]      { color: #94a3b8; font-size: 0.78rem; }
h2, h3, h4                         { color: #f1f5f9; }
.signal-card {
    padding: 10px 14px;
    border-radius: 8px;
    margin: 4px 0;
    font-weight: 600;
    font-size: 0.85rem;
}
.rsi-bar {
    height: 6px;
    border-radius: 3px;
    background: linear-gradient(90deg, #3b82f6 0%, #22c55e 50%, #ef4444 100%);
}
</style>
"""

# ── Helper functions ──────────────────────────────────────────────────────────


def rsi_zone(rsi: float | None) -> tuple[str, str]:
    """Returns (label, color) for RSI value."""
    if rsi is None:
        return ("N/D", "#64748b")
    if rsi >= 70:
        return ("Overbought", "#ef4444")
    if rsi >= 55:
        return ("Bullish", "#22c55e")
    if rsi >= 45:
        return ("Neutral", "#94a3b8")
    if rsi >= 30:
        return ("Bearish", "#f59e0b")
    return ("Oversold", "#3b82f6")


def macd_signal(macd: float | None, signal: float | None) -> tuple[str, str]:
    if macd is None or signal is None:
        return ("N/D", "#64748b")
    if macd > signal:
        return ("Bullish", "#22c55e")
    return ("Bearish", "#ef4444")


def ma_trend(close: float | None, ema50: float | None, ema200: float | None) -> str:
    if close is None or ema50 is None or ema200 is None:
        return "N/D"
    above50 = close > ema50
    above200 = close > ema200
    golden = ema50 > ema200
    if above50 and above200 and golden:
        return "Bull Trend"
    if not above50 and not above200 and not golden:
        return "Bear Trend"
    if above50 and not above200:
        return "Mixed +"
    return "Mixed -"


def ma_trend_color(label: str) -> str:
    return {
        "Bull Trend": "#22c55e",
        "Mixed +":    "#60a5fa",
        "N/D":        "#64748b",
        "Mixed -":    "#f59e0b",
        "Bear Trend": "#ef4444",
    }.get(label, "#94a3b8")


def fmt_mktcap(v: float | None) -> str:
    if v is None:
        return "N/D"
    if v >= 1e12:
        return f"{v/1e12:.1f}T"
    if v >= 1e9:
        return f"{v/1e9:.0f}B"
    if v >= 1e6:
        return f"{v/1e6:.0f}M"
    return str(v)


@st.cache_data(ttl=900)
def load_cached_screener() -> dict:
    """Load screener data from GitHub raw (cached 15 min)."""
    url = f"{GITHUB_RAW}/data/tv_screener.json"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


@st.cache_data(ttl=600)
def fetch_live_screener() -> dict:
    """Fetch directly from TradingView API (fallback when JSON is empty)."""
    try:
        data = fetch_tv_screener()
        if data:
            return {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "tickers": data,
                "source": "live",
            }
    except Exception:
        pass
    return {}


def load_screener_data() -> tuple[dict, str]:
    """Returns (tickers_dict, updated_at_str). Falls back to live TV fetch."""
    cached = load_cached_screener()
    tickers = cached.get("tickers", {})

    # Fallback: fetch live if JSON is empty or stale
    if not tickers:
        live = fetch_live_screener()
        tickers = live.get("tickers", {})
        cached = live

    updated = cached.get("updated_at", "")
    source_tag = " [live]" if cached.get("source") == "live" else ""
    if updated:
        try:
            dt = datetime.fromisoformat(updated).strftime("%d/%m/%Y %H:%M UTC") + source_tag
        except Exception:
            dt = updated + source_tag
    else:
        dt = "mai"
    return tickers, dt


def tradingview_chart_html(tv_symbol: str) -> str:
    return f"""
<div class="tradingview-widget-container" style="height:430px;width:100%;">
  <div class="tradingview-widget-container__widget" style="height:398px;width:100%;"></div>
  <script type="text/javascript"
    src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
    async>
  {{
    "width": "100%",
    "height": "398",
    "symbol": "{tv_symbol}",
    "interval": "D",
    "timezone": "Etc/UTC",
    "theme": "dark",
    "style": "1",
    "locale": "en",
    "allow_symbol_change": false,
    "calendar": false,
    "support_host": "https://www.tradingview.com"
  }}
  </script>
</div>
"""


def mini_gauge_html(value: float | None, label: str, color: str) -> str:
    pct = 50 if value is None else int(min(100, max(0, (value + 1) / 2 * 100)))
    return f"""
<div style="text-align:center;padding:6px 0;">
  <div style="font-size:0.7rem;color:#94a3b8;margin-bottom:4px;">{label}</div>
  <div style="background:#1e293b;border-radius:6px;height:8px;width:100%;overflow:hidden;">
    <div style="width:{pct}%;height:100%;background:{color};border-radius:6px;"></div>
  </div>
  <div style="font-size:0.85rem;color:{color};font-weight:700;margin-top:4px;">{value:.2f if value is not None else 'N/D'}</div>
</div>
"""


# ── Main app ──────────────────────────────────────────────────────────────────


def main() -> None:
    st.markdown(DARK_CSS, unsafe_allow_html=True)

    # ── Header ───────────────────────────────────────────────────────────────
    col_h1, col_h2, col_h3 = st.columns([5, 2, 1])
    with col_h1:
        st.markdown("## 📡 TradingView Stock Screener")
        st.caption(
            "Segnali tecnici live: RSI · MACD · EMA · Oscillatori · "
            "Rating composito TradingView"
        )
    with col_h2:
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        st.metric("Ora", now_str)
    with col_h3:
        refresh = st.button("⟳ Aggiorna", use_container_width=True)

    st.divider()

    # ── Load data ─────────────────────────────────────────────────────────────
    if refresh:
        load_cached_screener.clear()

    tickers_data, updated_at = load_screener_data()

    if not tickers_data:
        st.warning(
            "Nessun dato disponibile. Eseguire `python scripts/tradingview_screener.py` "
            "oppure attendere il prossimo run del workflow GitHub Actions."
        )
        st.stop()

    # ── Sidebar filters ───────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### Filtri Screener")

        all_sectors = sorted({UNIVERSE[t]["sector"] for t in UNIVERSE})
        sel_sectors = st.multiselect(
            "Settore",
            all_sectors,
            default=all_sectors,
            key="sectors",
        )

        all_exchanges = sorted({UNIVERSE[t]["exchange"] for t in UNIVERSE})
        sel_exchanges = st.multiselect(
            "Exchange",
            all_exchanges,
            default=all_exchanges,
            key="exchanges",
        )

        all_ratings = ["Strong Buy", "Buy", "Neutral", "Sell", "Strong Sell", "N/D"]
        sel_ratings = st.multiselect(
            "Rating TV",
            all_ratings,
            default=all_ratings,
            key="ratings",
        )

        st.markdown("---")
        rsi_min, rsi_max = st.slider("Range RSI", 0, 100, (0, 100), key="rsi_range")

        st.markdown("---")
        sort_by = st.selectbox(
            "Ordina per",
            ["Rating TV ↓", "RSI ↑", "RSI ↓", "Var% ↓", "Var% ↑", "Ticker A-Z"],
            key="sort_by",
        )

        st.markdown("---")
        st.caption(f"Dati aggiornati: {updated_at}")
        st.caption("Fonte: TradingView Scanner API")

    # ── Build dataframe ───────────────────────────────────────────────────────
    rows = []
    for ticker, info in UNIVERSE.items():
        d = tickers_data.get(ticker, {})
        rec = d.get("recommend_all")
        rsi = d.get("rsi")
        rat = rating_label(rec)
        rsi_lbl, _ = rsi_zone(rsi)
        macd_lbl, _ = macd_signal(d.get("macd"), d.get("macd_signal"))
        trend = ma_trend(d.get("close"), d.get("ema50"), d.get("ema200"))

        if info["sector"] not in sel_sectors:
            continue
        if info["exchange"] not in sel_exchanges:
            continue
        if rat not in sel_ratings:
            continue
        if rsi is not None and not (rsi_min <= rsi <= rsi_max):
            continue

        rows.append({
            "Ticker":      ticker,
            "TV Symbol":   d.get("tv_symbol", TV_TICKER_MAP.get(ticker, ticker)),
            "Exchange":    info["exchange"],
            "Settore":     info["sector"],
            "Rating TV":   rat,
            "Score":       rec,
            "RSI":         rsi,
            "RSI Zona":    rsi_lbl,
            "MACD":        macd_lbl,
            "MA Trend":    trend,
            "Prezzo":      d.get("close"),
            "Var%":        d.get("change_pct"),
            "ADX":         d.get("adx"),
            "Stoch K":     d.get("stoch_k"),
            "CCI":         d.get("cci"),
            "Rel. Vol":    d.get("relative_volume"),
            "P/E":         d.get("pe_ratio"),
            "Mkt Cap":     d.get("market_cap"),
            "_rec_all":    rec,
            "_rec_ma":     d.get("recommend_ma"),
            "_rec_osc":    d.get("recommend_oscillators"),
        })

    sort_map = {
        "Rating TV ↓": ("Score",  False),
        "RSI ↑":       ("RSI",    True),
        "RSI ↓":       ("RSI",    False),
        "Var% ↓":      ("Var%",   False),
        "Var% ↑":      ("Var%",   True),
        "Ticker A-Z":  ("Ticker", True),
    }
    sort_col, sort_asc = sort_map[sort_by]
    df = (
        pd.DataFrame(rows)
        .sort_values(sort_col, ascending=sort_asc, na_position="last")
        .reset_index(drop=True)
    )

    # ── Summary cards ─────────────────────────────────────────────────────────
    counts = df["Rating TV"].value_counts()
    c1, c2, c3, c4, c5 = st.columns(5)
    for col, lbl, emoji in [
        (c1, "Strong Buy",  "🟢"),
        (c2, "Buy",         "🔵"),
        (c3, "Neutral",     "⚪"),
        (c4, "Sell",        "🟡"),
        (c5, "Strong Sell", "🔴"),
    ]:
        col.metric(f"{emoji} {lbl}", counts.get(lbl, 0))

    st.divider()

    # ── Signal Distribution Chart ─────────────────────────────────────────────
    col_chart1, col_chart2 = st.columns([3, 2])

    with col_chart1:
        st.markdown("#### Distribuzione Rating")
        if not df.empty:
            rat_order = ["Strong Buy", "Buy", "Neutral", "Sell", "Strong Sell"]
            rat_colors = ["#22c55e", "#60a5fa", "#94a3b8", "#f59e0b", "#ef4444"]
            rat_counts = [counts.get(r, 0) for r in rat_order]
            fig_bar = go.Figure(go.Bar(
                x=rat_order,
                y=rat_counts,
                marker_color=rat_colors,
                text=rat_counts,
                textposition="outside",
            ))
            fig_bar.update_layout(
                template="plotly_dark",
                paper_bgcolor="#0f172a",
                plot_bgcolor="#1e293b",
                height=220,
                margin=dict(l=0, r=0, t=10, b=0),
                yaxis=dict(gridcolor="#334155"),
                showlegend=False,
            )
            st.plotly_chart(fig_bar, use_container_width=True)

    with col_chart2:
        st.markdown("#### RSI Distribution")
        rsi_vals = df["RSI"].dropna().tolist()
        if rsi_vals:
            fig_rsi = go.Figure(go.Histogram(
                x=rsi_vals,
                nbinsx=10,
                marker_color="#3b82f6",
                opacity=0.8,
            ))
            fig_rsi.add_vline(x=70, line_dash="dash", line_color="#ef4444", annotation_text="OB 70")
            fig_rsi.add_vline(x=30, line_dash="dash", line_color="#22c55e", annotation_text="OS 30")
            fig_rsi.update_layout(
                template="plotly_dark",
                paper_bgcolor="#0f172a",
                plot_bgcolor="#1e293b",
                height=220,
                margin=dict(l=0, r=0, t=10, b=0),
                showlegend=False,
                yaxis=dict(gridcolor="#334155"),
            )
            st.plotly_chart(fig_rsi, use_container_width=True)

    st.divider()

    # ── Main Screener Table + Detail ──────────────────────────────────────────
    st.markdown(f"#### Screener — {len(df)} titoli")

    col_table, col_detail = st.columns([3, 2])

    display_cols = [
        "Ticker", "Exchange", "Settore",
        "Rating TV", "Score",
        "RSI", "RSI Zona", "MACD",
        "MA Trend", "Prezzo", "Var%",
        "ADX", "Stoch K", "Rel. Vol",
    ]
    display_df = df[display_cols].copy()

    def _style_rating(val: str) -> str:
        bg, fg = RATING_COLORS.get(val, ("#1e293b", "#f1f5f9"))
        return f"background-color:{bg};color:{fg};font-weight:700"

    def _style_score(val: float) -> str:
        if val is None or pd.isna(val):
            return ""
        if val >= 0.5:
            return "color:#22c55e;font-weight:700"
        if val >= 0.1:
            return "color:#60a5fa"
        if val > -0.1:
            return "color:#94a3b8"
        if val > -0.5:
            return "color:#f59e0b"
        return "color:#ef4444;font-weight:700"

    def _style_change(val: float) -> str:
        if val is None or pd.isna(val):
            return ""
        return "color:#22c55e" if val >= 0 else "color:#ef4444"

    def _style_macd(val: str) -> str:
        if val == "Bullish":
            return "color:#22c55e"
        if val == "Bearish":
            return "color:#ef4444"
        return "color:#64748b"

    def _style_rsi(val: float) -> str:
        if val is None or pd.isna(val):
            return ""
        if val >= 70:
            return "color:#ef4444;font-weight:700"
        if val <= 30:
            return "color:#3b82f6;font-weight:700"
        return ""

    styled = (
        display_df.style
        .map(_style_rating, subset=["Rating TV"])
        .map(_style_score,  subset=["Score"])
        .map(_style_change, subset=["Var%"])
        .map(_style_macd,   subset=["MACD"])
        .map(_style_rsi,    subset=["RSI"])
        .format({
            "Score":    lambda v: f"{v:+.3f}" if v == v else "N/D",
            "RSI":      lambda v: f"{v:.1f}"  if v == v else "N/D",
            "Prezzo":   lambda v: f"{v:.2f}"  if v == v else "N/D",
            "Var%":     lambda v: f"{v:+.2f}%" if v == v else "N/D",
            "ADX":      lambda v: f"{v:.1f}"  if v == v else "N/D",
            "Stoch K":  lambda v: f"{v:.1f}"  if v == v else "N/D",
            "Rel. Vol": lambda v: f"{v:.2f}x" if v == v else "N/D",
        }, na_rep="N/D")
    )

    with col_table:
        selected_ticker = st.selectbox(
            "Seleziona titolo per dettaglio e grafico",
            df["Ticker"].tolist(),
            key="selected_ticker",
        )
        st.dataframe(styled, use_container_width=True, hide_index=True, height=520)

    # ── Detail Panel ──────────────────────────────────────────────────────────
    with col_detail:
        if selected_ticker and selected_ticker in df["Ticker"].values:
            row = df[df["Ticker"] == selected_ticker].iloc[0]
            d = tickers_data.get(selected_ticker, {})
            tv_sym = row["TV Symbol"]

            st.markdown(f"#### {selected_ticker} — {UNIVERSE[selected_ticker]['sector']}")

            # Mini signal cards
            bg, fg = RATING_COLORS.get(row["Rating TV"], ("#1e293b", "#f1f5f9"))
            emoji = RATING_EMOJI.get(row["Rating TV"], "⚫")
            st.markdown(
                f'<div class="signal-card" style="background:{bg};color:{fg};">'
                f'{emoji} {row["Rating TV"]} &nbsp;|&nbsp; Score: {row["Score"]:+.3f}'
                f"</div>",
                unsafe_allow_html=True,
            )

            # 3 gauge bars (Overall / MA / Oscillators)
            g1, g2, g3 = st.columns(3)
            rec_all = row["_rec_all"]
            rec_ma  = row["_rec_ma"]
            rec_osc = row["_rec_osc"]

            def _gauge_color(v):
                if v is None:
                    return "#64748b"
                if v >= 0.1:
                    return "#22c55e"
                if v <= -0.1:
                    return "#ef4444"
                return "#94a3b8"

            with g1:
                st.markdown(
                    mini_gauge_html(rec_all, "Overall", _gauge_color(rec_all)),
                    unsafe_allow_html=True,
                )
            with g2:
                st.markdown(
                    mini_gauge_html(rec_ma, "MA", _gauge_color(rec_ma)),
                    unsafe_allow_html=True,
                )
            with g3:
                st.markdown(
                    mini_gauge_html(rec_osc, "Oscillatori", _gauge_color(rec_osc)),
                    unsafe_allow_html=True,
                )

            # Key metrics table
            close_price = d.get("close")
            ema50  = d.get("ema50")
            ema200 = d.get("ema200")
            bb_up  = d.get("bb_upper")
            bb_dn  = d.get("bb_lower")

            def _fmt(v, decimals=2):
                if v is None:
                    return "N/D"
                return f"{v:.{decimals}f}"

            metrics = {
                "Prezzo":     _fmt(close_price),
                "EMA 50":     _fmt(ema50),
                "EMA 200":    _fmt(ema200),
                "BB Upper":   _fmt(bb_up),
                "BB Lower":   _fmt(bb_dn),
                "RSI":        _fmt(d.get("rsi"), 1),
                "Stoch K/D":  f"{_fmt(d.get('stoch_k'),1)} / {_fmt(d.get('stoch_d'),1)}",
                "ADX":        _fmt(d.get("adx"), 1),
                "CCI":        _fmt(d.get("cci"), 1),
                "P/E":        _fmt(d.get("pe_ratio"), 1),
                "Mkt Cap":    fmt_mktcap(d.get("market_cap")),
                "Rel. Vol":   f"{d.get('relative_volume') or 0:.2f}x",
            }
            st.table(pd.DataFrame(
                {"Indicatore": list(metrics.keys()), "Valore": list(metrics.values())}
            ).set_index("Indicatore"))

            # TradingView advanced chart embed
            st.markdown("**Grafico TradingView**")
            components.html(tradingview_chart_html(tv_sym), height=440)

    st.divider()

    # ── Top Picks ─────────────────────────────────────────────────────────────
    st.markdown("#### Top 5 per Rating")
    top5 = df.head(5)
    if not top5.empty:
        cols_top = st.columns(len(top5))
        for i, (_, r) in enumerate(top5.iterrows()):
            bg, fg = RATING_COLORS.get(r["Rating TV"], ("#1e293b", "#f1f5f9"))
            emoji = RATING_EMOJI.get(r["Rating TV"], "⚫")
            rsi_v = r["RSI"]
            rsi_str = f"{rsi_v:.1f}" if pd.notna(rsi_v) else "N/D"
            var_v = r["Var%"]
            var_str = f"{var_v:+.2f}%" if pd.notna(var_v) else "N/D"
            with cols_top[i]:
                st.markdown(
                    f'<div style="background:{bg};color:{fg};border-radius:10px;'
                    f'padding:12px;text-align:center;">'
                    f'<div style="font-size:1.1rem;font-weight:700">{r["Ticker"]}</div>'
                    f'<div style="font-size:0.75rem;color:#94a3b8">{r["Settore"]}</div>'
                    f'<div style="margin-top:8px;">{emoji} {r["Rating TV"]}</div>'
                    f'<div style="font-size:0.8rem;margin-top:4px;">RSI {rsi_str}</div>'
                    f'<div style="font-size:0.8rem;">Var {var_str}</div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # ── Footer ────────────────────────────────────────────────────────────────
    st.divider()
    st.caption(
        f"Dati TradingView aggiornati: {updated_at} · "
        "GitHub Actions workflow: giornaliero 05:30 UTC · "
        "Fonte: [TradingView](https://www.tradingview.com)"
    )

    # Auto-refresh every 5 min
    time.sleep(300)
    st.rerun()


if __name__ == "__main__":
    main()
