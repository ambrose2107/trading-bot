from core.strategy_base import BaseStrategy

class MyNewStrategy(BaseStrategy):
    def __init__(self, broker):
        super().__init__(broker, name="my_new_strategy")
        self.watchlist = ["AAPL", "MSFT"]

    def get_symbols(self):
        return self.watchlist

    async def generate_signals(self):
        signals = []
        # your logic here
        return signals