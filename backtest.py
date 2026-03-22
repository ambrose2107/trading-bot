import pandas as pd
import numpy as np
from brokers.alpaca_adapter import alpaca_broker
from core.logger import get_logger

log = get_logger("backtest")

class Backtester:
    def __init__(self, symbol, days=365, starting_cash=10000):
        self.symbol = symbol
        self.days = days
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.shares = 0
        self.trades = []
        self.equity_curve = []

    def run_ma_crossover(self, fast=50, slow=200):
        bars = alpaca_broker.get_bars(self.symbol, timeframe="1Day", limit=self.days + slow)
        df = pd.DataFrame(bars)
        df["close"] = pd.to_numeric(df["close"])
        df["ma_fast"] = df["close"].rolling(fast).mean()
        df["ma_slow"] = df["close"].rolling(slow).mean()
        df = df.dropna().reset_index(drop=True)
        return self._simulate(df)

    def run_rsi(self, period=14, oversold=30, overbought=70):
        import ta
        bars = alpaca_broker.get_bars(self.symbol, timeframe="1Day", limit=self.days + period)
        df = pd.DataFrame(bars)
        df["close"] = pd.to_numeric(df["close"])
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=period).rsi()
        df = df.dropna().reset_index(drop=True)
        for i in range(1, len(df)):
            price = df["close"].iloc[i]
            rsi_now = df["rsi"].iloc[i]
            rsi_prev = df["rsi"].iloc[i-1]
            ts = str(df["timestamp"].iloc[i]) if "timestamp" in df.columns else str(i)
            if rsi_prev < oversold and rsi_now >= oversold and self.shares == 0:
                qty = int(self.cash * 0.95 / price)
                if qty > 0:
                    self._buy(price, qty, ts, f"RSI={rsi_now:.1f} recovering")
            elif rsi_prev > overbought and rsi_now <= overbought and self.shares > 0:
                self._sell(price, self.shares, ts, f"RSI={rsi_now:.1f} pulling back")
            self.equity_curve.append({"date": ts, "equity": self.cash + self.shares * price})
        return self._results()

    def _simulate(self, df):
        for i in range(1, len(df)):
            price = df["close"].iloc[i]
            ma_fast = df["ma_fast"].iloc[i]
            ma_slow = df["ma_slow"].iloc[i]
            prev_fast = df["ma_fast"].iloc[i-1]
            prev_slow = df["ma_slow"].iloc[i-1]
            ts = str(df["timestamp"].iloc[i]) if "timestamp" in df.columns else str(i)
            if prev_fast <= prev_slow and ma_fast > ma_slow and self.shares == 0:
                qty = int(self.cash * 0.95 / price)
                if qty > 0:
                    self._buy(price, qty, ts, "Golden cross")
            elif prev_fast >= prev_slow and ma_fast < ma_slow and self.shares > 0:
                self._sell(price, self.shares, ts, "Death cross")
            self.equity_curve.append({"date": ts, "equity": self.cash + self.shares * price})
        return self._results()

    def _buy(self, price, qty, ts, reason):
        self.cash -= price * qty
        self.shares += qty
        self.trades.append({"date": ts, "side": "BUY", "qty": qty, "price": price, "value": price*qty, "reason": reason})

    def _sell(self, price, qty, ts, reason):
        entry = next((t["price"] for t in reversed(self.trades) if t["side"] == "BUY"), price)
        pnl = (price - entry) * qty
        self.cash += price * qty
        self.shares -= qty
        self.trades.append({"date": ts, "side": "SELL", "qty": qty, "price": price, "value": price*qty, "reason": reason, "pnl": pnl})

    def _results(self):
        last_price = self.trades[-1]["price"] if self.trades else 0
        final_equity = self.cash + self.shares * last_price
        sell_trades = [t for t in self.trades if t["side"] == "SELL"]
        winning = [t for t in sell_trades if t.get("pnl", 0) > 0]
        losing = [t for t in sell_trades if t.get("pnl", 0) <= 0]
        total_pnl = sum(t.get("pnl", 0) for t in sell_trades)
        win_rate = len(winning) / len(sell_trades) * 100 if sell_trades else 0
        return {
            "symbol": self.symbol,
            "starting_cash": self.starting_cash,
            "final_equity": round(final_equity, 2),
            "total_return_pct": round((final_equity - self.starting_cash) / self.starting_cash * 100, 2),
            "total_pnl": round(total_pnl, 2),
            "total_trades": len(self.trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate_pct": round(win_rate, 2),
        }
