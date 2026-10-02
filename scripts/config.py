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
    "ULVR.L":  {"exchange": "FTSE",   "currency": "GBp", "sector": "Consumer"},
    "HSBA.L":  {"exchange": "FTSE",   "currency": "GBp", "sector": "Financial"},
    "BP.L":    {"exchange": "FTSE",   "currency": "GBp", "sector": "Energy"},
    "GSK.L":   {"exchange": "FTSE",   "currency": "GBp", "sector": "Healthcare"},
    "RIO.L":   {"exchange": "FTSE",   "currency": "GBp", "sector": "Materials"},
    "ENI.MI":  {"exchange": "BIT",    "currency": "EUR", "sector": "Energy"},
    "ISP.MI":  {"exchange": "BIT",    "currency": "EUR", "sector": "Financial"},
    "ENEL.MI": {"exchange": "BIT",    "currency": "EUR", "sector": "Utilities"},
    "LDO.MI":  {"exchange": "BIT",    "currency": "EUR", "sector": "Aerospace"},
    "MONC.MI": {"exchange": "BIT",    "currency": "EUR", "sector": "Consumer"},
}

INITIAL_CAPITAL = 3000.0
REBALANCE_THRESHOLD = 0.05

STRATEGIES = ["equal_weight", "momentum", "fundamental", "sentiment"]

STRATEGY_LABELS = {
    "equal_weight": "Equal Weight",
    "momentum": "Momentum",
    "fundamental": "Fundamental",
    "sentiment": "Sentiment",
}

FX_FALLBACK = {"USD": 0.92, "GBP": 1.17, "GBp": 0.0117, "EUR": 1.0}

# Costo di transazione simulato (commissione + slippage), in punti base sul
# controvalore di ogni ordine. 10 bps = 0.10%. Applicato solo ai nuovi trade.
TRANSACTION_COST_BPS = 10.0

# Tasso risk-free annuo usato per Sharpe/Sortino (approssimazione BTP/Bund breve).
RISK_FREE_RATE = 0.02

# Benchmark confrontati con le strategie (ticker Yahoo Finance -> etichetta).
# Sono serie "total return" (prezzi aggiustati / ETF ad accumulazione): i dividendi sono
# gia' reinvestiti. Quelli in valuta estera vengono convertiti in EUR con i cambi storici.
BENCHMARKS = {
    "SWDA.MI": "MSCI World (EUR)",
    "SPY": "S&P 500 (in EUR)",
}
BENCHMARK_CURRENCIES = {"SWDA.MI": "EUR", "SPY": "USD"}

# Ticker Yahoo per lo storico dei cambi verso EUR (usati per ricostruire l'equity).
FX_HISTORY_TICKERS = {"USD": "USDEUR=X", "GBP": "GBPEUR=X"}
