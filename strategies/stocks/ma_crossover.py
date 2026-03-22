import pandas as pd
from core.strategy_base import BaseStrategy
from core.risk_engine import risk_engine


class MovingAverageCrossover(BaseStrategy):
    """
    Classic MA Crossover Strategy.

    BUY signal:  50-day MA crosses ABOVE 200-day MA (golden cross)
    SELL signal: 50-day MA crosses BELOW 200-day MA (death cross)

    Safe, simple, and a great starting point.
    """

    def __init__(self, broker):
        super().__init__(broker, name="ma_crossover")
        self.fast_period = 50
        self.slow_period = 200
        self.watchlist = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
            "TSLA", "META", "SPY", "QQQ"
        ]

    def get_symbols(self) -> list[str]:
        return self.watchlist

    async def generate_signals(self) -> list[dict]:
        signals = []
        account = self.broker.get_account()
        equity  = account["equity"]
        positions = {p["symbol"]: p for p in self.broker.get_positions()}

        for symbol in self.watchlist:
            try:
                bars = self.broker.get_bars(symbol, timeframe="1Day", limit=250)
                if len(bars) < self.slow_period + 5:
                    continue

                df = pd.DataFrame(bars)
                df["close"] = pd.to_numeric(df["close"])
                df["ma_fast"] = df["close"].rolling(self.fast_period).mean()
                df["ma_slow"] = df["close"].rolling(self.slow_period).mean()

                # Latest and previous values
                curr_fast = df["ma_fast"].iloc[-1]
                curr_slow = df["ma_slow"].iloc[-1]
                prev_fast = df["ma_fast"].iloc[-2]
                prev_slow = df["ma_slow"].iloc[-2]

                current_price = df["close"].iloc[-1]
                in_position   = symbol in positions

                # Golden cross — BUY
                if prev_fast <= prev_slow and curr_fast > curr_slow and not in_position:
                    qty = risk_engine.calculate_position_size(equity, current_price)
                    signals.append({
                        "symbol": symbol,
                        "action": "buy",
                        "qty":    qty,
                        "reason": f"Golden cross: MA{self.fast_period} crossed above MA{self.slow_period}"
                    })
                    self.log.info(f"SIGNAL BUY {symbol}: Golden cross detected")

                # Death cross — SELL
                elif prev_fast >= prev_slow and curr_fast < curr_slow and in_position:
                    qty = int(positions[symbol]["qty"])
                    signals.append({
                        "symbol": symbol,
                        "action": "sell",
                        "qty":    qty,
                        "reason": f"Death cross: MA{self.fast_period} crossed below MA{self.slow_period}"
                    })
                    self.log.info(f"SIGNAL SELL {symbol}: Death cross detected")

            except Exception as e:
                self.log.error(f"Error analysing {symbol}: {e}")

        return signals
