"""Backtest storico delle strategie basate sui prezzi, con benchmark.

Cosa viene testato
------------------
Solo le strategie i cui segnali sono ricostruibili *point-in-time* dai prezzi:
equal_weight, momentum, trend_momentum, inverse_volatility. Le strategie
fundamental e sentiment usano dati (bilanci, news) di cui non esiste uno storico
affidabile e gratuito: includerle introdurrebbe look-ahead bias, quindi restano
fuori. I segnali sono calcolati usando solo i prezzi fino al giorno di
ribilanciamento; gli ordini incidono sui rendimenti dal giorno successivo.

Semplificazioni dichiarate: azioni frazionarie (il paper trading live usa lotti
interi su 3.000 EUR), costo di transazione proporzionale al turnover, cassa a
rendimento zero, prezzi "Adj Close" convertiti in EUR con il cambio giornaliero.

Uso:
    python scripts/backtest.py --years 5
"""
import argparse
import json
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from config import INITIAL_CAPITAL, UNIVERSE  # noqa: E402
from metrics import TRADING_DAYS, summarize  # noqa: E402
from strategies import (  # noqa: E402
    EqualWeightStrategy,
    InverseVolatilityStrategy,
    MomentumStrategy,
    RiskManagedStrategy,
    TrendMomentumStrategy,
)

BENCHMARKS = {"SPY": "USD", "FTSEMIB.MI": "EUR"}
FX_TICKERS = {"USD": "EURUSD=X", "GBP": "EURGBP=X", "GBp": "EURGBP=X"}

MOMENTUM_WINDOW = 63
VOL_WINDOW = 60
TREND_WINDOW = 200


def default_strategies() -> dict:
    return {
        "equal_weight": EqualWeightStrategy(),
        "momentum": MomentumStrategy(),
        "trend_momentum": TrendMomentumStrategy(),
        "inverse_volatility": InverseVolatilityStrategy(),
        # stessa strategia + tetti 15% per titolo e 35% per settore: misura se aiutano
        "momentum_risk": RiskManagedStrategy(MomentumStrategy()),
    }


def build_signals(history: pd.DataFrame) -> dict:
    """Segnali calcolati usando SOLO le righe di `history` (prezzi in EUR)."""
    signals: dict = {"momentum": {}, "volatility": {}, "trend": {}}
    rets = history.pct_change().dropna(how="all")
    for ticker in history.columns:
        px = history[ticker].dropna()
        if len(px) > MOMENTUM_WINDOW:
            signals["momentum"][ticker] = {
                "return_3m": float(px.iloc[-1] / px.iloc[-1 - MOMENTUM_WINDOW] - 1.0)
            }
        r = rets[ticker].dropna().iloc[-VOL_WINDOW:]
        if len(r) >= 20:
            signals["volatility"][ticker] = {
                "vol_60d": float(r.std() * math.sqrt(TRADING_DAYS))
            }
        if len(px) >= TREND_WINDOW:
            signals["trend"][ticker] = {
                "above_ma200": bool(px.iloc[-1] > px.iloc[-TREND_WINDOW:].mean())
            }
    return signals


def run_backtest(
    prices_eur: pd.DataFrame,
    strategies: dict,
    universe: dict | None = None,
    rebalance_every: int = 21,
    cost_bps: float = 10.0,
    warmup: int = TREND_WINDOW,
    initial: float = INITIAL_CAPITAL,
) -> dict[str, pd.Series]:
    """Simula ogni strategia. Ritorna {nome: equity curve in EUR} dal giorno
    `warmup` in poi (servono 200 giorni di storia per il filtro di trend)."""
    universe = universe or {t: UNIVERSE.get(t, {}) for t in prices_eur.columns}
    prices_eur = prices_eur.ffill()
    returns = prices_eur.pct_change().fillna(0.0)
    dates = prices_eur.index
    if len(dates) <= warmup + 1:
        raise ValueError(
            f"Storico insufficiente: {len(dates)} giorni, ne servono > {warmup + 1}"
        )

    curves: dict[str, pd.Series] = {}
    for name, strategy in strategies.items():
        cash = initial
        holdings = {t: 0.0 for t in prices_eur.columns}
        values = []
        for i in range(warmup, len(dates)):
            if i > warmup:  # applica il rendimento del giorno alle posizioni
                for t in holdings:
                    holdings[t] *= 1.0 + returns[t].iloc[i]
            total = cash + sum(holdings.values())
            if (i - warmup) % rebalance_every == 0:
                signals = build_signals(prices_eur.iloc[: i + 1])
                weights = strategy.compute_weights(universe, {}, signals)
                weights = {t: w for t, w in weights.items() if t in holdings}
                target = {t: total * weights.get(t, 0.0) for t in holdings}
                turnover = sum(abs(target[t] - holdings[t]) for t in holdings)
                total -= turnover * cost_bps / 10_000.0
                target = {t: (total * weights.get(t, 0.0)) for t in holdings}
                holdings = target
                cash = total - sum(holdings.values())
            values.append(cash + sum(holdings.values()))
        curves[name] = pd.Series(values, index=dates[warmup:], name=name)
    return curves


def buy_and_hold(prices_eur: pd.Series, start, initial: float = INITIAL_CAPITAL):
    px = prices_eur.ffill().loc[start:]
    return (px / px.iloc[0] * initial).rename(prices_eur.name)


def download_prices_eur(
    tickers: dict[str, str], years: int
) -> tuple[pd.DataFrame, list[str]]:
    """Scarica Adj Close da Yahoo e converte in EUR. `tickers` = {ticker: valuta}.
    Ritorna (DataFrame, ticker_non_scaricati)."""
    import yfinance as yf

    fx_needed = {FX_TICKERS[c] for c in tickers.values() if c in FX_TICKERS}
    symbols = sorted(set(tickers) | fx_needed)
    raw = yf.download(
        symbols, period=f"{years}y", auto_adjust=True, progress=False, threads=True
    )["Close"]
    if isinstance(raw, pd.Series):
        raw = raw.to_frame(symbols[0])
    raw = raw.ffill()

    out, missing = {}, []
    for ticker, currency in tickers.items():
        if ticker not in raw or raw[ticker].dropna().empty:
            missing.append(ticker)
            continue
        px = raw[ticker]
        if currency == "GBp":
            px = px / 100.0
        if currency in FX_TICKERS:
            fx = raw.get(FX_TICKERS[currency])
            if fx is None or fx.dropna().empty:
                missing.append(ticker)
                continue
            px = px / fx
        out[ticker] = px
    frame = pd.DataFrame(out).dropna(how="all")
    return frame, missing


def subperiod_metrics(
    curves: dict[str, pd.Series], splits: int = 2
) -> list[dict]:
    """Metriche su `splits` sottoperiodi consecutivi di uguale lunghezza.

    Non e' un walk-forward (le strategie hanno parametri fissi, niente da
    ri-ottimizzare): misura la *stabilita'*. Una strategia brillante in un solo
    sottoperiodo e' probabilmente fortuna, non un vantaggio.
    """
    first = next(iter(curves.values()))
    n = len(first)
    bounds = [round(i * n / splits) for i in range(splits + 1)]
    out = []
    for k in range(splits):
        lo, hi = bounds[k], min(bounds[k + 1] + 1, n)  # +1: parte dall'ultimo punto
        start, end = first.index[lo], first.index[hi - 1]
        # slicing per DATA: i benchmark hanno calendari di borsa diversi
        out.append(
            {
                "start": str(start.date()),
                "end": str(end.date()),
                "metrics": {
                    name: summarize(s.loc[start:end].tolist())
                    for name, s in curves.items()
                },
            }
        )
    return out


def format_markdown(
    results: dict[str, dict], meta: dict, subperiods: list[dict] | None = None
) -> str:
    lines = [
        "# Backtest",
        "",
        f"Periodo: {meta['start']} → {meta['end']} · capitale iniziale "
        f"{meta['initial']:.0f} € · ribilanciamento ogni {meta['rebalance_every']} "
        f"giorni · costi {meta['cost_bps']:.0f} bps sul turnover · valori in EUR.",
        "",
        "| Strategia | Rend. totale | CAGR | Volatilità | Sharpe | Sortino | Max DD | Calmar |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, m in results.items():
        lines.append(
            f"| {name} | {m['total_return']:+.1%} | {m['cagr']:+.1%} | "
            f"{m['volatility']:.1%} | {m['sharpe']:.2f} | {m['sortino']:.2f} | "
            f"-{m['max_drawdown']:.1%} | {m['calmar']:.2f} |"
        )
    if subperiods:
        lines += ["", "## Stabilità per sottoperiodo", ""]
        header = "| Strategia | " + " | ".join(
            f"{p['start']} → {p['end']}" for p in subperiods
        ) + " |"
        lines += [header, "|---|" + "---:|" * len(subperiods)]
        for name in results:
            cells = []
            for p in subperiods:
                m = p["metrics"][name]
                cells.append(f"{m['total_return']:+.1%} · Sharpe {m['sharpe']:.2f}")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += [
        "",
        "Le strategie `fundamental` e `sentiment` non sono incluse: non esiste uno "
        "storico point-in-time gratuito dei loro segnali e il backtest avrebbe "
        "look-ahead bias. I risultati passati non garantiscono quelli futuri.",
        "",
    ]
    return "\n".join(lines)


def save_chart(curves: dict[str, pd.Series], path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    for name, s in curves.items():
        ax.plot(s.index, s.values, label=name, linewidth=1.4)
    ax.set_title("Equity curve (EUR)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest strategie + benchmark")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--rebalance-every", type=int, default=21)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--splits", type=int, default=2, help="sottoperiodi di stabilita'")
    parser.add_argument("--out-dir", default=os.path.join(
        os.path.dirname(__file__), "..", "docs"))
    args = parser.parse_args()

    ccy = {t: info["currency"] for t, info in UNIVERSE.items()}
    prices, missing = download_prices_eur(ccy, args.years)
    if missing:
        print(f"[WARN] ticker non scaricati, esclusi: {missing}")
    if prices.empty:
        raise SystemExit("[ERROR] nessun prezzo scaricato")
    universe = {t: UNIVERSE[t] for t in prices.columns}

    curves = run_backtest(
        prices,
        default_strategies(),
        universe,
        rebalance_every=args.rebalance_every,
        cost_bps=args.cost_bps,
    )
    start = next(iter(curves.values())).index[0]

    bench_prices, bench_missing = download_prices_eur(BENCHMARKS, args.years)
    if bench_missing:
        print(f"[WARN] benchmark non scaricati: {bench_missing}")
    for b in bench_prices.columns:
        curves[f"benchmark:{b}"] = buy_and_hold(bench_prices[b], start)

    results = {n: summarize(s.tolist()) for n, s in curves.items()}
    subperiods = subperiod_metrics(curves, args.splits)
    meta = {
        "start": str(start.date()),
        "end": str(next(iter(curves.values())).index[-1].date()),
        "initial": INITIAL_CAPITAL,
        "rebalance_every": args.rebalance_every,
        "cost_bps": args.cost_bps,
    }
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "backtest.json"), "w") as f:
        json.dump(
            {"meta": meta, "metrics": results, "subperiods": subperiods}, f, indent=2
        )
        f.write("\n")
    with open(os.path.join(args.out_dir, "backtest.md"), "w", encoding="utf-8") as f:
        f.write(format_markdown(results, meta, subperiods))
    save_chart(curves, os.path.join(args.out_dir, "backtest.png"))
    print(format_markdown(results, meta, subperiods))


if __name__ == "__main__":
    main()
