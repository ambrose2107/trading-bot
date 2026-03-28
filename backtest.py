"""
Backtester — run strategies against historical data.
Uses start= date parameter (not limit=) for reliable data fetching.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from brokers.alpaca_adapter import alpaca_broker
from core.logger import get_logger

log = get_logger("backtest")


class Backtester:
    def __init__(self, symbol: str, days: int = 365, starting_cash: float = 10000):
        self.symbol = symbol
        self.days = days
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.shares = 0
        self.trades = []
        self.equity_curve = []

    def _fetch_df(self, extra_bars=300):
        """Fetch OHLCV data using start date — reliable on free Alpaca tier."""
        start = (datetime.now() - timedelta(days=self.days + extra_bars)).strftime(
            "%Y-%m-%d"
        )
        df = alpaca_broker.api.get_bars(
            self.symbol, "1Day", start=start, limit=self.days + extra_bars
        ).df
        df = df.reset_index()
        df.columns = [str(c).lower() for c in df.columns]
        # Find timestamp column
        ts_col = next((c for c in df.columns if "time" in c), None)
        if ts_col:
            df["date"] = df[ts_col].astype(str).str[:10]
        else:
            df["date"] = [str(i) for i in range(len(df))]
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col])
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"])
        return df

    def _calc_rsi(self, close, period=14):
        """Manual RSI — no external library needed."""
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, float("nan"))
        return 100 - (100 / (1 + rs))

    def run_ma_crossover(self, fast: int = 50, slow: int = 200):
        log.info(f"Backtest MA({fast}/{slow}) on {self.symbol}")
        df = self._fetch_df(extra_bars=slow + 50)
        df["close"] = pd.to_numeric(df["close"])
        df["ma_fast"] = df["close"].rolling(fast).mean()
        df["ma_slow"] = df["close"].rolling(slow).mean()
        df = df.dropna().reset_index(drop=True)

        self.cash = self.starting_cash
        self.shares = 0
        self.trades = []
        self.equity_curve = []

        for i in range(1, len(df)):
            price = df["close"].iloc[i]
            ma_fast = df["ma_fast"].iloc[i]
            ma_slow = df["ma_slow"].iloc[i]
            prev_fast = df["ma_fast"].iloc[i - 1]
            prev_slow = df["ma_slow"].iloc[i - 1]
            date = df["date"].iloc[i]

            # Golden cross — buy
            if prev_fast <= prev_slow and ma_fast > ma_slow and self.shares == 0:
                qty = int(self.cash * 0.95 / price)
                if qty > 0:
                    self._buy(price, qty, date, f"Golden cross MA{fast}>MA{slow}")
            # Death cross — sell
            elif prev_fast >= prev_slow and ma_fast < ma_slow and self.shares > 0:
                self._sell(price, self.shares, date, f"Death cross MA{fast}<MA{slow}")

            self.equity_curve.append(
                {"date": date, "equity": round(self.cash + self.shares * price, 2)}
            )

        return self._results()

    def run_rsi(self, period: int = 14, oversold: int = 30, overbought: int = 70):
        log.info(f"Backtest RSI({period}) on {self.symbol}")
        df = self._fetch_df(extra_bars=period + 50)
        df["close"] = pd.to_numeric(df["close"])
        df["rsi"] = self._calc_rsi(df["close"], period)
        df = df.dropna().reset_index(drop=True)

        self.cash = self.starting_cash
        self.shares = 0
        self.trades = []
        self.equity_curve = []

        for i in range(1, len(df)):
            price = df["close"].iloc[i]
            rsi_now = df["rsi"].iloc[i]
            rsi_prev = df["rsi"].iloc[i - 1]
            date = df["date"].iloc[i]

            if rsi_prev < oversold and rsi_now >= oversold and self.shares == 0:
                qty = int(self.cash * 0.95 / price)
                if qty > 0:
                    self._buy(
                        price, qty, date, f"RSI={rsi_now:.1f} recovering from oversold"
                    )
            elif rsi_prev > overbought and rsi_now <= overbought and self.shares > 0:
                self._sell(
                    price,
                    self.shares,
                    date,
                    f"RSI={rsi_now:.1f} pulling back from overbought",
                )

            self.equity_curve.append(
                {"date": date, "equity": round(self.cash + self.shares * price, 2)}
            )

        return self._results()

    def run_macd(self, fast=12, slow=26, signal=9):
        log.info(f"Backtest MACD({fast},{slow},{signal}) on {self.symbol}")
        df = self._fetch_df(extra_bars=slow + 50)
        df["close"] = pd.to_numeric(df["close"])
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        df["macd"] = ema_fast - ema_slow
        df["signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
        df["hist"] = df["macd"] - df["signal"]
        df = df.dropna().reset_index(drop=True)

        self.cash = self.starting_cash
        self.shares = 0
        self.trades = []
        self.equity_curve = []

        for i in range(1, len(df)):
            price = df["close"].iloc[i]
            macd_now = df["macd"].iloc[i]
            macd_prev = df["macd"].iloc[i - 1]
            sig_now = df["signal"].iloc[i]
            sig_prev = df["signal"].iloc[i - 1]
            date = df["date"].iloc[i]

            if (
                macd_prev < sig_prev
                and macd_now > sig_now
                and df["hist"].iloc[i] > 0
                and self.shares == 0
            ):
                qty = int(self.cash * 0.95 / price)
                if qty > 0:
                    self._buy(price, qty, date, f"MACD bullish cross")
            elif macd_prev > sig_prev and macd_now < sig_now and self.shares > 0:
                self._sell(price, self.shares, date, f"MACD bearish cross")

            self.equity_curve.append(
                {"date": date, "equity": round(self.cash + self.shares * price, 2)}
            )

        return self._results()

    def run_supertrend(self, atr_period=10, multiplier=3.0):
        log.info(f"Backtest Supertrend({atr_period},{multiplier}) on {self.symbol}")
        df = self._fetch_df(extra_bars=atr_period + 50)
        for col in ["close", "high", "low", "open"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col])

        # ATR calculation
        hl2 = (df["high"] + df["low"]) / 2
        tr = pd.concat(
            [
                df["high"] - df["low"],
                abs(df["high"] - df["close"].shift(1)),
                abs(df["low"] - df["close"].shift(1)),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(atr_period).mean()
        ub = (hl2 + multiplier * atr).tolist()
        lb = (hl2 - multiplier * atr).tolist()
        cl = df["close"].tolist()
        n = len(df)

        direction = [1] * n
        for i in range(1, n):
            if lb[i] is None or ub[i] is None:
                continue
            if cl[i] > (ub[i - 1] or 0):
                direction[i] = 1
            elif cl[i] < (lb[i - 1] or 0):
                direction[i] = -1
            else:
                direction[i] = direction[i - 1]
                if direction[i] == 1 and lb[i] < lb[i - 1]:
                    lb[i] = lb[i - 1]
                if direction[i] == -1 and ub[i] > ub[i - 1]:
                    ub[i] = ub[i - 1]

        df = df.iloc[atr_period:].reset_index(drop=True)
        direction = direction[atr_period:]

        self.cash = self.starting_cash
        self.shares = 0
        self.trades = []
        self.equity_curve = []

        for i in range(1, len(df)):
            price = df["close"].iloc[i]
            date = df["date"].iloc[i]
            dir_now = direction[i]
            dir_prev = direction[i - 1]

            if dir_prev == -1 and dir_now == 1 and self.shares == 0:
                qty = int(self.cash * 0.95 / price)
                if qty > 0:
                    self._buy(price, qty, date, "Supertrend flip bullish")
            elif dir_prev == 1 and dir_now == -1 and self.shares > 0:
                self._sell(price, self.shares, date, "Supertrend flip bearish")

            self.equity_curve.append(
                {"date": date, "equity": round(self.cash + self.shares * price, 2)}
            )

        return self._results()

    def _buy(self, price, qty, date, reason=""):
        self.cash -= qty * price
        self.shares += qty
        self.trades.append(
            {
                "date": date,
                "side": "BUY",
                "qty": qty,
                "price": round(price, 2),
                "reason": reason,
                "pnl": None,
                "value": round(qty * price, 2),
            }
        )

    def _sell(self, price, qty, date, reason=""):
        entry = next(
            (t["price"] for t in reversed(self.trades) if t["side"] == "BUY"), price
        )
        pnl = round((price - entry) * qty, 2)
        self.cash += qty * price
        self.shares -= qty
        self.trades.append(
            {
                "date": date,
                "side": "SELL",
                "qty": qty,
                "price": round(price, 2),
                "reason": reason,
                "pnl": pnl,
                "value": round(qty * price, 2),
            }
        )

    def _results(self) -> dict:
        final = self.cash + self.shares * (
            self.trades[-1]["price"] if self.trades else self.starting_cash
        )
        sells = [t for t in self.trades if t["side"] == "SELL"]
        wins = [t for t in sells if (t.get("pnl") or 0) > 0]
        total_pnl = sum(t.get("pnl", 0) or 0 for t in sells)
        return {
            "symbol": self.symbol,
            "starting_cash": self.starting_cash,
            "final_equity": round(final, 2),
            "total_return_pct": round(
                (final - self.starting_cash) / self.starting_cash * 100, 2
            ),
            "total_pnl": round(total_pnl, 2),
            "total_trades": len(self.trades),
            "winning_trades": len(wins),
            "losing_trades": len(sells) - len(wins),
            "win_rate_pct": round(len(wins) / len(sells) * 100, 2) if sells else 0,
        }
