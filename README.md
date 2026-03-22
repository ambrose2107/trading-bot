# Algo Trading System

Automated stock trading bot with a live web dashboard.
Built with Python, FastAPI, Alpaca Markets API.

## Setup in 5 steps

### 1. Get Alpaca API keys
- Go to https://alpaca.markets and create a free account
- Navigate to "API Keys" in the dashboard
- Generate a new key pair (use Paper Trading to start)
- Copy your API Key and Secret Key

### 2. Set environment variables
```
# In Replit: go to Secrets (lock icon) and add:
ALPACA_API_KEY     = your_key_here
ALPACA_SECRET_KEY  = your_secret_here
ALPACA_MODE        = paper
APP_SECRET_KEY     = any_random_string
DASHBOARD_PASSWORD = your_password
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run
```bash
python main.py
```

### 5. Open dashboard
Go to your Replit URL (or http://localhost:8000)

---

## Project structure

```
trading-system/
├── core/
│   ├── config.py          # All settings loaded from env
│   ├── database.py        # SQLite DB + models
│   ├── logger.py          # Logging setup
│   ├── risk_engine.py     # Safety checks before every order
│   └── strategy_base.py   # Base class all strategies inherit
├── brokers/
│   └── alpaca_adapter.py  # Alpaca API wrapper (swap for IBKR/Binance later)
├── strategies/
│   ├── stocks/
│   │   ├── ma_crossover.py   # Moving average crossover
│   │   └── rsi_strategy.py   # RSI mean reversion
│   ├── options/           # Empty — Phase 2
│   └── crypto/            # Empty — Phase 3
├── dashboard/
│   ├── server.py          # FastAPI backend
│   └── index.html         # Web UI (monitor from iPad)
├── bot.py                 # Main bot scheduler
├── main.py                # Entry point
└── requirements.txt
```

---

## Strategies included

### MA Crossover (ma_crossover)
Classic golden/death cross strategy.
- BUY: 50-day MA crosses above 200-day MA
- SELL: 50-day MA crosses below 200-day MA
- Good for: trending markets

### RSI Strategy (rsi_strategy)
Mean reversion using RSI indicator.
- BUY: RSI recovers above 30 (was oversold)
- SELL: RSI drops below 70 (was overbought)
- Good for: sideways/ranging markets

---

## Safety features

- Kill switch (one click, all trading stops)
- Daily loss limit (auto-stops if down 5%)
- Max position limit (never holds more than 5 stocks)
- Max position size (never risks more than 2% per trade)
- Emergency close (closes ALL positions instantly)
- Paper trading mode (no real money risk)

---

## Expanding to Options (Phase 2)
Add a file: `brokers/ibkr_adapter.py`
Add strategies in: `strategies/options/`
No changes needed to core/, risk_engine, or dashboard.

## Expanding to Crypto (Phase 3)
Add a file: `brokers/binance_adapter.py`
Add strategies in: `strategies/crypto/`
Same pattern.
