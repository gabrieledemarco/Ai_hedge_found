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
