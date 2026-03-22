import pandas as pd
import ta
from core.strategy_base import BaseStrategy
from core.risk_engine import risk_engine


class RSIStrategy(BaseStrategy):
    """
    RSI Mean Reversion Strategy.

    BUY  when RSI drops below 30 (oversold — likely to bounce up)
    SELL when RSI rises above 70 (overbought — likely to pull back)

    Works best in range-bound (sideways) markets.
    """

    def __init__(self, broker):
        super().__init__(broker, name="rsi_strategy")
        self.rsi_period   = 14
        self.oversold     = 30
        self.overbought   = 70
        self.watchlist    = ["AAPL", "MSFT", "SPY", "QQQ", "AMZN"]

    def get_symbols(self) -> list[str]:
        return self.watchlist

    async def generate_signals(self) -> list[dict]:
        signals  = []
        account  = self.broker.get_account()
        equity   = account["equity"]
        positions = {p["symbol"]: p for p in self.broker.get_positions()}

        for symbol in self.watchlist:
            try:
                bars = self.broker.get_bars(symbol, timeframe="1Day", limit=50)
                if len(bars) < self.rsi_period + 2:
                    continue

                df = pd.DataFrame(bars)
                df["close"] = pd.to_numeric(df["close"])
                df["rsi"]   = ta.momentum.RSIIndicator(df["close"], window=self.rsi_period).rsi()

                rsi_now  = df["rsi"].iloc[-1]
                rsi_prev = df["rsi"].iloc[-2]
                price    = df["close"].iloc[-1]
                in_pos   = symbol in positions

                # Oversold — BUY
                if rsi_prev < self.oversold and rsi_now >= self.oversold and not in_pos:
                    qty = risk_engine.calculate_position_size(equity, price)
                    signals.append({
                        "symbol": symbol,
                        "action": "buy",
                        "qty":    qty,
                        "reason": f"RSI recovering from oversold (RSI={rsi_now:.1f})"
                    })

                # Overbought — SELL
                elif rsi_prev > self.overbought and rsi_now <= self.overbought and in_pos:
                    qty = int(positions[symbol]["qty"])
                    signals.append({
                        "symbol": symbol,
                        "action": "sell",
                        "qty":    qty,
                        "reason": f"RSI pulling back from overbought (RSI={rsi_now:.1f})"
                    })

            except Exception as e:
                self.log.error(f"Error in RSI for {symbol}: {e}")

        return signals
