import pandas as pd
import numpy as np
from core.strategy_base import BaseStrategy


class MACDStrategy(BaseStrategy):
    """
    MACD Crossover Strategy
    Buy when MACD line crosses above Signal line (bullish momentum)
    Sell when MACD crosses below Signal line (bearish momentum)
    """

    def __init__(self, broker):
        super().__init__(broker, name="macd_strategy")
        self.watchlist = [
            "AAPL",
            "MSFT",
            "NVDA",
            "AMZN",
            "GOOGL",
            "META",
            "TSLA",
            "SPY",
        ]
        self.fast_period = 12
        self.slow_period = 26
        self.signal_period = 9
        self.risk_per_trade = 0.015  # 1.5% of capital per trade

    def get_symbols(self):
        return self.watchlist

    async def generate_signals(self):
        signals = []
        account = self.broker.get_account()
        equity = float(account["equity"])
        positions = {p["symbol"]: p for p in self.broker.get_positions()}

        for symbol in self.watchlist:
            try:
                bars = self.broker.get_bars(symbol, timeframe="1Day", limit=150)
                if len(bars) < 40:
                    continue

                df = pd.DataFrame(bars)
                df["close"] = pd.to_numeric(df["close"])

                # MACD calculation
                ema_fast = df["close"].ewm(span=self.fast_period).mean()
                ema_slow = df["close"].ewm(span=self.slow_period).mean()
                macd_line = ema_fast - ema_slow
                signal_line = macd_line.ewm(span=self.signal_period).mean()
                histogram = macd_line - signal_line

                price = df["close"].iloc[-1]
                macd_now = macd_line.iloc[-1]
                macd_prev = macd_line.iloc[-2]
                signal_now = signal_line.iloc[-1]
                signal_prev = signal_line.iloc[-2]
                hist_now = histogram.iloc[-1]

                in_position = symbol in positions

                # Bullish crossover: MACD crosses above signal
                bullish_cross = macd_prev < signal_prev and macd_now > signal_now
                # Extra filter: histogram turning positive and MACD below zero (early entry)
                strong_bull = bullish_cross and hist_now > 0

                # Bearish crossover: MACD crosses below signal
                bearish_cross = macd_prev > signal_prev and macd_now < signal_now

                if strong_bull and not in_position:
                    qty = max(1, int((equity * self.risk_per_trade) / price))
                    signals.append(
                        {
                            "symbol": symbol,
                            "action": "buy",
                            "qty": qty,
                            "reason": f"MACD bullish cross | MACD={macd_now:.3f} Signal={signal_now:.3f}",
                        }
                    )
                    self.log.info(f"BUY {symbol} qty={qty} MACD cross up")

                elif bearish_cross and in_position:
                    qty = int(float(positions[symbol]["qty"]))
                    signals.append(
                        {
                            "symbol": symbol,
                            "action": "sell",
                            "qty": qty,
                            "reason": f"MACD bearish cross | MACD={macd_now:.3f} Signal={signal_now:.3f}",
                        }
                    )
                    self.log.info(f"SELL {symbol} MACD cross down")

            except Exception as e:
                self.log.error(f"MACD error {symbol}: {e}")

        return signals
