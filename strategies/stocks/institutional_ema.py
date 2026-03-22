
import pandas as pd
import numpy as np
from core.strategy_base import BaseStrategy
from core.risk_engine import risk_engine


class InstitutionalEMAStrategy(BaseStrategy):

    def __init__(self, broker):
        super().__init__(broker, name="institutional_ema")
        self.watchlist = [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
            "META", "TSLA", "SPY", "QQQ"
        ]
        self.ema_fast = 9
        self.ema_mid = 21
        self.ema_slow = 50
        self.ema_trend = 200
        self.risk_per_trade = 0.01

    def get_symbols(self):
        return self.watchlist

    def calculate_atr(self, df, period=14):
        df["high"]  = pd.to_numeric(df["high"])
        df["low"]   = pd.to_numeric(df["low"])
        df["close"] = pd.to_numeric(df["close"])
        df["tr1"] = df["high"] - df["low"]
        df["tr2"] = abs(df["high"] - df["close"].shift())
        df["tr3"] = abs(df["low"]  - df["close"].shift())
        df["tr"]  = df[["tr1","tr2","tr3"]].max(axis=1)
        df["atr"] = df["tr"].rolling(period).mean()
        return df["atr"]

    async def generate_signals(self):
        signals  = []
        account  = self.broker.get_account()
        equity   = float(account["equity"])
        positions = {p["symbol"]: p for p in self.broker.get_positions()}

        for symbol in self.watchlist:
            try:
                bars = self.broker.get_bars(symbol, timeframe="1Day", limit=300)
                if len(bars) < 210:
                    continue
                df = pd.DataFrame(bars)
                df["close"] = pd.to_numeric(df["close"])
                df["ema9"]   = df["close"].ewm(span=9).mean()
                df["ema21"]  = df["close"].ewm(span=21).mean()
                df["ema50"]  = df["close"].ewm(span=50).mean()
                df["ema200"] = df["close"].ewm(span=200).mean()
                df["atr"]    = self.calculate_atr(df)

                price    = df["close"].iloc[-1]
                ema9     = df["ema9"].iloc[-1]
                ema21    = df["ema21"].iloc[-1]
                ema50    = df["ema50"].iloc[-1]
                ema200   = df["ema200"].iloc[-1]
                atr      = df["atr"].iloc[-1]
                prev_ema9  = df["ema9"].iloc[-2]
                prev_ema21 = df["ema21"].iloc[-2]
                in_position = symbol in positions

                bullish_trend  = price > ema200 and ema50 > ema200
                pullback       = abs(price - ema21) / price < 0.015
                bullish_cross  = prev_ema9 < prev_ema21 and ema9 > ema21
                valid_vol      = atr / price > 0.01

                if bullish_trend and pullback and bullish_cross and valid_vol and not in_position:
                    stop_loss      = price - (1.5 * atr)
                    risk_per_share = price - stop_loss
                    qty = int((equity * self.risk_per_trade) / risk_per_share)
                    if qty <= 0:
                        continue
                    signals.append({
                        "symbol": symbol, "action": "buy", "qty": qty,
                        "reason": "EMA setup: trend + pullback + momentum"
                    })
                    self.log.info(f"BUY {symbol} | Qty:{qty} | SL:{stop_loss:.2f}")

                elif in_position:
                    entry_price    = float(positions[symbol]["avg_entry"])
                    trailing_stop  = entry_price - (1.5 * atr)
                    bearish_cross  = prev_ema9 > prev_ema21 and ema9 < ema21
                    trend_break    = price < ema200
                    if bearish_cross or trend_break or price < trailing_stop:
                        qty = int(float(positions[symbol]["qty"]))
                        signals.append({
                            "symbol": symbol, "action": "sell", "qty": qty,
                            "reason": "Exit: EMA cross / trend break / trailing stop"
                        })
                        self.log.info(f"SELL {symbol} | Exit triggered")

            except Exception as e:
                self.log.error(f"Error analysing {symbol}: {e}")

        return signals
