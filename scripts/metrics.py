"""Metriche di performance (nessun I/O), usate da backtest, dashboard e test.

Convenzioni: i rendimenti sono frazioni (0.01 = 1%), 252 giorni di borsa/anno.

Il modulo ha due livelli:
  * primitive su liste di valori (`daily_returns`, `sharpe`, `max_drawdown`, `summarize`,
    `history_metrics`...), usate dal backtest e dalle dashboard live;
  * serie di equity datate (`build_equity_series`, `daily_series`, `compute_metrics`...),
    usate dalla dashboard statica: la serie viene ricostruita dove il portafoglio era
    sottovalutato per prezzi mancanti o cambio instabile.
"""
import math
from datetime import datetime

TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# Primitive su liste di valori
# ---------------------------------------------------------------------------


def daily_returns(values: list[float]) -> list[float]:
    """Rendimenti semplici tra valori consecutivi di una equity curve."""
    return [
        values[i] / values[i - 1] - 1.0
        for i in range(1, len(values))
        if values[i - 1] > 0
    ]


def total_return(values: list[float]) -> float:
    if len(values) < 2 or values[0] <= 0:
        return 0.0
    return values[-1] / values[0] - 1.0


def cagr(values: list[float], periods_per_year: int = TRADING_DAYS) -> float:
    """Rendimento annualizzato composto. 0.0 se la serie e' troppo corta."""
    n = len(values) - 1
    if n < 1 or values[0] <= 0 or values[-1] <= 0:
        return 0.0
    return (values[-1] / values[0]) ** (periods_per_year / n) - 1.0


def annualized_vol(rets: list[float], periods_per_year: int = TRADING_DAYS) -> float:
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(periods_per_year)


def sharpe(
    rets: list[float], risk_free: float = 0.0, periods_per_year: int = TRADING_DAYS
) -> float:
    """Sharpe annualizzato: media dei rendimenti in eccesso / dev. standard."""
    if len(rets) < 2:
        return 0.0
    rf = risk_free / periods_per_year
    excess = [r - rf for r in rets]
    vol = annualized_vol(excess, periods_per_year)
    if vol < 1e-12:  # serie costante: evita rapporti dominati dal rumore float
        return 0.0
    return (sum(excess) / len(excess)) * periods_per_year / vol


def sortino(
    rets: list[float], risk_free: float = 0.0, periods_per_year: int = TRADING_DAYS
) -> float:
    """Come lo Sharpe ma penalizza solo la volatilita' al ribasso."""
    if len(rets) < 2:
        return 0.0
    rf = risk_free / periods_per_year
    excess = [r - rf for r in rets]
    downside = [min(0.0, r) for r in excess]
    dd = math.sqrt(sum(d * d for d in downside) / len(downside)) * math.sqrt(
        periods_per_year
    )
    if dd < 1e-12:
        return 0.0
    return (sum(excess) / len(excess)) * periods_per_year / dd


def max_drawdown(values: list[float]) -> float:
    """Massimo drawdown come frazione positiva (0.2 = -20% dal picco)."""
    if not values:
        return 0.0
    peak = values[0]
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak)
    return worst


def calmar(values: list[float], periods_per_year: int = TRADING_DAYS) -> float:
    mdd = max_drawdown(values)
    return cagr(values, periods_per_year) / mdd if mdd > 0 else 0.0


def summarize(values: list[float], risk_free: float = 0.0) -> dict[str, float]:
    """Tutte le metriche in un dict, pronto per tabelle e JSON."""
    rets = daily_returns(values)
    return {
        "total_return": total_return(values),
        "cagr": cagr(values),
        "volatility": annualized_vol(rets),
        "sharpe": sharpe(rets, risk_free),
        "sortino": sortino(rets, risk_free),
        "max_drawdown": max_drawdown(values),
        "calmar": calmar(values),
    }


def collapse_to_daily(history: list[dict]) -> list[float]:
    """Una valutazione per giorno (l'ultima): il live registra ~3 iterazioni al
    giorno, e trattarle come "giorni" falserebbe annualizzazione e Sharpe."""
    by_day: dict[str, float] = {}
    for i, entry in enumerate(history):
        # senza timestamp ogni voce vale come un giorno a se'
        day = str(entry.get("timestamp", i))[:10]
        by_day[day] = entry["total_value_eur"]
    return list(by_day.values())


def history_metrics(history: list[dict]) -> dict:
    """Metriche per le dashboard a partire da `iterations_log`.

    Percentuali espresse in punti percentuali (12.5 = 12.5%), come si aspettano
    i template HTML. Le metriche di rischio usano un valore per giorno; `values`
    resta la serie completa per i grafici.
    """
    if not history:
        return {}
    values = [e["total_value_eur"] for e in history]
    daily = collapse_to_daily(history)
    rets = daily_returns(daily)
    gains = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    mdd = max_drawdown(daily)
    ann = cagr(daily)
    return {
        "total_return": total_return(values) * 100,
        "ann_return": ann * 100,
        "ann_vol": annualized_vol(rets) * 100,
        "sharpe": sharpe(rets),
        "sortino": sortino(rets),
        "max_drawdown": mdd * 100,
        "calmar": ann / mdd if mdd > 0 else 0.0,
        "win_rate": len(gains) / len(rets) * 100 if rets else 0.0,
        "profit_factor": abs(sum(gains) / sum(losses)) if losses else float("inf"),
        "n_entries": len(values),
        "n_days": len(daily),
        "initial": values[0],
        "final": values[-1],
        "daily_rets": [r * 100 for r in rets],
        "values": values,
    }


# ---------------------------------------------------------------------------
# Serie di equity datate (dashboard statica)
# ---------------------------------------------------------------------------


def _price_on_or_before(days: dict, day: str):
    """Ultimo prezzo storico con data <= day, altrimenti il primo successivo."""
    if not days:
        return None
    earlier = [d for d in days if d <= day]
    if earlier:
        return days[max(earlier)]
    return days[min(days)]


def fx_rate(ccy: str, day: str, entry_fx: dict | None, price_history: dict, fallback: dict) -> float:
    """Cambio verso EUR: dalla voce di log, poi dallo storico FX, poi dal fallback statico."""
    if ccy == "EUR":
        return 1.0
    if ccy == "GBp":
        return fx_rate("GBP", day, entry_fx, price_history, fallback) / 100.0
    if entry_fx and entry_fx.get(ccy):
        return entry_fx[ccy]
    hist = _price_on_or_before(price_history.get(f"FX:{ccy}", {}), day)
    return hist if hist else fallback.get(ccy, 1.0)


def build_equity_series(
    history: list,
    price_history: dict | None = None,
    universe: dict | None = None,
    fx_fallback: dict | None = None,
    dividends: dict | None = None,
) -> list:
    """Converte `iterations_log` in [{timestamp, date, value, repaired, div_cum}].

    Ogni voce viene rivalutata da zero: cassa + sum(quantita' x prezzo x cambio).
    Questo corregge due problemi storici del totale registrato:
      * titoli senza prezzo contati 0 EUR (crolli artificiali di centinaia di euro);
      * cambio USD/GBP instabile: quando Alpha Vantage non rispondeva si usava un
        fallback statico (0.92) invece del tasso reale, gonfiando le posizioni USA.
    Prezzo: quello usato nella voce, altrimenti la chiusura storica del giorno, altrimenti
    l'ultimo noto, altrimenti il prezzo di carico. Cambio: quello registrato nella voce,
    altrimenti lo storico FX del giorno, altrimenti il fallback statico.
    `repaired` e' True se il valore ricalcolato differisce di oltre 1 EUR da quello
    registrato. I dati grezzi del portafoglio non vengono modificati.

    `dividends` ({ticker: {data ex-dividend: importo per azione in valuta locale}}) permette
    di stimare i dividendi che la simulazione NON ha accreditato in cassa: per ogni data
    ex-dividend si contano le azioni in portafoglio nella voce precedente. `div_cum` e' il
    totale cumulato in EUR (stima, esclude le tasse); `value` resta quello della simulazione.
    """
    price_history = price_history or {}
    universe = universe or {}
    fx_fallback = fx_fallback or {"EUR": 1.0}
    dividends = dividends or {}

    series = []
    last_local: dict[str, float] = {}
    div_cum = 0.0
    prev_day, prev_positions = None, {}
    for entry in history:
        ts = entry.get("timestamp", "")
        day = ts[:10]
        if prev_day is not None:
            for ticker, by_date in dividends.items():
                held = (prev_positions.get(ticker) or {}).get("shares", 0)
                if held <= 0:
                    continue
                ccy = universe.get(ticker, {}).get("currency", "EUR")
                for ex_date, amount in by_date.items():
                    if prev_day < ex_date <= day:
                        div_cum += held * amount * fx_rate(ccy, ex_date, None, price_history, fx_fallback)
        used = entry.get("prices_used", {}) or {}
        entry_fx = entry.get("fx_rates")
        recorded = float(entry.get("total_value_eur", 0.0))

        value = float(entry.get("current_cash", 0.0))
        for ticker, pos in (entry.get("positions") or {}).items():
            shares = pos.get("shares", 0)
            local = used.get(ticker)
            if not local:
                local = _price_on_or_before(price_history.get(ticker, {}), day)
            if not local:
                local = last_local.get(ticker)
            ccy = universe.get(ticker, {}).get("currency", "EUR")
            if local:
                value += shares * local * fx_rate(ccy, day, entry_fx, price_history, fx_fallback)
            else:
                value += shares * pos.get("avg_price", 0.0)

        for ticker, price in used.items():
            if price and price > 0:
                last_local[ticker] = price
        series.append(
            {
                "timestamp": ts,
                "date": day,
                "value": round(value, 2),
                "repaired": abs(value - recorded) > 1.0,
                "div_cum": round(div_cum, 2),
            }
        )
        prev_day, prev_positions = day, entry.get("positions") or {}
    return series


def daily_series(series: list) -> list:
    """Un punto per giorno: l'ultimo valore registrato. Ritorna [(date_str, value)]."""
    by_day: dict[str, float] = {}
    for p in series:
        by_day[p["date"]] = p["value"]
    return sorted(by_day.items())


def daily_series_with_dividends(series: list) -> list:
    """Come daily_series, ma sommando i dividendi cumulati stimati: [(date, value + div_cum)]."""
    by_day: dict[str, float] = {}
    for p in series:
        by_day[p["date"]] = p["value"] + p.get("div_cum", 0.0)
    return sorted(by_day.items())


def _mean(xs: list) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _sample_std(xs: list) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def relative_metrics(daily: list, bench: list, risk_free: float = 0.0, min_obs: int = 20) -> dict | None:
    """Metriche rispetto a un benchmark, su [(date, value)] allineate sulle date in comune.

    Beta, correlazione, alpha annualizzato (CAPM semplice), tracking error, information
    ratio e cattura dei rialzi/ribassi. None se le osservazioni comuni sono troppo poche:
    con pochi mesi di storico i valori sono rumorosi e vanno letti come indicativi.
    """
    sd, bd = dict(daily), dict(bench)
    dates = sorted(set(sd) & set(bd))
    if len(dates) < min_obs + 1:
        return None
    rs, rb = [], []
    for i in range(1, len(dates)):
        s0, s1, b0, b1 = sd[dates[i - 1]], sd[dates[i]], bd[dates[i - 1]], bd[dates[i]]
        if s0 > 0 and b0 > 0:
            rs.append(s1 / s0 - 1.0)
            rb.append(b1 / b0 - 1.0)
    n = len(rs)
    if n < min_obs:
        return None

    mean_s, mean_b = _mean(rs), _mean(rb)
    std_s, std_b = _sample_std(rs), _sample_std(rb)
    cov = sum((x - mean_s) * (y - mean_b) for x, y in zip(rs, rb)) / (n - 1)
    beta = cov / (std_b**2) if std_b > 0 else None
    corr = cov / (std_s * std_b) if std_s > 0 and std_b > 0 else None
    rf_d = risk_free / TRADING_DAYS
    alpha = (
        ((mean_s - rf_d) - beta * (mean_b - rf_d)) * TRADING_DAYS if beta is not None else None
    )
    active = [x - y for x, y in zip(rs, rb)]
    te = _sample_std(active) * math.sqrt(TRADING_DAYS)
    ir = _mean(active) * TRADING_DAYS / te if te > 1e-12 else None

    def capture(sign: int):
        pairs = [(x, y) for x, y in zip(rs, rb) if y * sign > 0]
        if not pairs or abs(_mean([y for _, y in pairs])) < 1e-12:
            return None
        return _mean([x for x, _ in pairs]) / _mean([y for _, y in pairs])

    return {
        "n_obs": n,
        "beta": beta,
        "correlation": corr,
        "alpha": alpha,
        "tracking_error": te,
        "information_ratio": ir,
        "up_capture": capture(1),
        "down_capture": capture(-1),
    }


def max_drawdown_dated(daily: list) -> tuple:
    """(max drawdown come frazione positiva, data picco, data minimo) su [(date, value)]."""
    peak_v, peak_d = None, None
    worst, w_peak, w_trough = 0.0, None, None
    for d, v in daily:
        if peak_v is None or v > peak_v:
            peak_v, peak_d = v, d
        dd = (peak_v - v) / peak_v if peak_v else 0.0
        if dd > worst:
            worst, w_peak, w_trough = dd, peak_d, d
    return worst, w_peak, w_trough


def drawdown_series(daily: list) -> list:
    """[(date, drawdown)] con drawdown <= 0, rispetto al massimo corrente."""
    out, peak = [], None
    for d, v in daily:
        peak = v if peak is None or v > peak else peak
        out.append((d, (v / peak - 1.0) if peak else 0.0))
    return out


def compute_metrics(daily: list, risk_free: float = 0.0) -> dict:
    """Metriche su serie giornaliera [(date, value)]. Rendimenti in frazioni."""
    if len(daily) < 2:
        v = daily[0][1] if daily else 0.0
        return {"initial": v, "final": v, "total_return": 0.0, "n_days": len(daily)}

    dates = [d for d, _ in daily]
    values = [v for _, v in daily]
    initial, final = values[0], values[-1]
    total = final / initial - 1.0 if initial > 0 else 0.0

    d0 = datetime.strptime(dates[0], "%Y-%m-%d").date()
    d1 = datetime.strptime(dates[-1], "%Y-%m-%d").date()
    calendar_days = max((d1 - d0).days, 1)
    # Annualizzazione composta sui giorni di calendario; con storici brevi e' solo indicativa.
    ann_return = (1.0 + total) ** (365.0 / calendar_days) - 1.0 if total > -1 else -1.0

    rets = daily_returns(values)
    mdd, mdd_peak, mdd_trough = max_drawdown_dated(daily)
    cur_dd = drawdown_series(daily)[-1][1]

    gains = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    return {
        "initial": initial,
        "final": final,
        "total_return": total,
        "ann_return": ann_return,
        "ann_vol": annualized_vol(rets),
        "sharpe": sharpe(rets, risk_free),
        "sortino": sortino(rets, risk_free),
        "max_drawdown": mdd,
        "max_drawdown_peak": mdd_peak,
        "max_drawdown_trough": mdd_trough,
        "current_drawdown": cur_dd,
        "calmar": ann_return / mdd if mdd > 0 else 0.0,
        "win_rate": len(gains) / len(rets) if rets else 0.0,
        "profit_factor": (sum(gains) / abs(sum(losses))) if losses else None,
        "best_day": max(rets) if rets else 0.0,
        "worst_day": min(rets) if rets else 0.0,
        "last_day_return": rets[-1] if rets else 0.0,
        "n_days": len(daily),
        "calendar_days": calendar_days,
    }


def rebase(daily: list, base: float = 100.0) -> list:
    """Serie normalizzata: primo valore = base."""
    if not daily or daily[0][1] <= 0:
        return list(daily)
    first = daily[0][1]
    return [(d, v / first * base) for d, v in daily]
