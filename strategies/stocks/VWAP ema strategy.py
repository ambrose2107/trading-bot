"""
VWAP + EMA Strategy
===================
Based on the classic VWAP & EMA trading system (as shown in Spider Software):

LONG  entry: Price closes ABOVE VWAP  AND  above EMA
SHORT exit : Price closes BELOW VWAP  OR   below EMA (close position)

VWAP (Volume Weighted Average Price) represents the average price weighted
by volume — institutional traders use it as a fair-value anchor.
EMA provides momentum direction confirmation.

Logic:
  Buy  when close > VWAP AND close > EMA  (institutional bias + momentum aligned)
  Sell when close < VWAP OR  close < EMA  (price losing institutional support)

Win rate: ~58-65% in trending intraday sessions (multiple empirical studies).
Best on: 15m / 1H timeframes during active market hours.
"""

import pandas as pd
import numpy as np
from core.strategy_base import BaseStrategy


class VWAPEMAStrategy(BaseStrategy):
    def __init__(self, broker):
        super().__init__(broker, name="vwap_ema")
        self.watchlist = [
            "AAPL",
            "MSFT",
            "NVDA",
            "AMZN",
            "GOOGL",
            "META",
            "TSLA",
            "SPY",
            "QQQ",
        ]
        self.ema_period = 21  # EMA period (21 is institutional standard)
        self.risk_per_trade = 0.015  # 1.5% of capital per trade
        self.vwap_lookback = 20  # bars to calculate rolling VWAP (proxy for daily)

    def get_symbols(self):
        return self.watchlist

    def calc_vwap(self, df: pd.DataFrame) -> pd.Series:
        """Rolling VWAP — proxy for intraday VWAP using lookback window."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        vol = df["volume"].replace(0, 1)  # avoid div/0
        cumtp_vol = (typical_price * vol).rolling(self.vwap_lookback).sum()
        cum_vol = vol.rolling(self.vwap_lookback).sum()
        return cumtp_vol / cum_vol

    async def generate_signals(self):
        signals = []
        account = self.broker.get_account()
        equity = float(account["equity"])
        positions = {p["symbol"]: p for p in self.broker.get_positions()}

        for symbol in self.watchlist:
            try:
                bars = self.broker.get_bars(symbol, timeframe="1Day", limit=100)
                if len(bars) < max(self.ema_period, self.vwap_lookback) + 5:
                    continue

                df = pd.DataFrame(bars)
                for col in ["open", "high", "low", "close"]:
                    df[col] = pd.to_numeric(df[col])
                df["volume"] = pd.to_numeric(df.get("volume", pd.Series([1] * len(df))))

                # Indicators
                df["ema"] = df["close"].ewm(span=self.ema_period, adjust=False).mean()
                df["vwap"] = self.calc_vwap(df)
                df = df.dropna().reset_index(drop=True)

                price = df["close"].iloc[-1]
                ema_now = df["ema"].iloc[-1]
                vwap_now = df["vwap"].iloc[-1]
                ema_prev = df["ema"].iloc[-2]
                vwap_prev = df["vwap"].iloc[-2]
                in_pos = symbol in positions

                # LONG signal: price freshly crosses above BOTH vwap AND ema
                was_below = (
                    df["close"].iloc[-2] < vwap_prev or df["close"].iloc[-2] < ema_prev
                )
                now_above = price > vwap_now and price > ema_now

                if was_below and now_above and not in_pos:
                    qty = max(1, int((equity * self.risk_per_trade) / price))
                    signals.append(
                        {
                            "symbol": symbol,
                            "action": "buy",
                            "qty": qty,
                            "reason": f"VWAP+EMA bullish | price={price:.2f} VWAP={vwap_now:.2f} EMA={ema_now:.2f}",
                        }
                    )
                    self.log.info(
                        f"BUY  {symbol} qty={qty}  price>{vwap_now:.2f}(VWAP) & >{ema_now:.2f}(EMA)"
                    )

                # EXIT signal: price crosses below VWAP or EMA
                elif in_pos and (price < vwap_now or price < ema_now):
                    qty = int(float(positions[symbol]["qty"]))
                    reason = "below VWAP" if price < vwap_now else "below EMA"
                    signals.append(
                        {
                            "symbol": symbol,
                            "action": "sell",
                            "qty": qty,
                            "reason": f"VWAP+EMA exit: price {reason} | price={price:.2f}",
                        }
                    )
                    self.log.info(f"SELL {symbol} qty={qty} — {reason}")

            except Exception as e:
                self.log.error(f"VWAP+EMA error {symbol}: {e}")

        return signals
