from abc import ABC, abstractmethod
from core.logger import get_logger
from core.risk_engine import risk_engine


class BaseStrategy(ABC):
    """
    All strategies inherit from this.
    Expanding to options or crypto = new subclass, same interface.
    """

    def __init__(self, broker, name: str):
        self.broker  = broker
        self.name    = name
        self.enabled = True
        self.log     = get_logger(f"strategy.{name}")

    @abstractmethod
    def get_symbols(self) -> list[str]:
        """Return list of symbols this strategy trades."""
        pass

    @abstractmethod
    async def generate_signals(self) -> list[dict]:
        """
        Analyse market data and return a list of signals.
        Each signal: {"symbol": "AAPL", "action": "buy"/"sell", "qty": 5, "reason": "..."}
        """
        pass

    async def run(self):
        """Main loop — called by the scheduler every cycle."""
        if not self.enabled:
            return

        self.log.info(f"Running strategy: {self.name}")
        signals = await self.generate_signals()

        for signal in signals:
            await self._execute_signal(signal)

    async def _execute_signal(self, signal: dict):
        symbol = signal["symbol"]
        action = signal["action"]
        qty    = signal["qty"]

        # Get current price for risk check
        try:
            price = await self.broker.get_latest_price(symbol)
        except Exception as e:
            self.log.error(f"Could not get price for {symbol}: {e}")
            return

        # Risk gate
        ok, reason = risk_engine.check_order(symbol, action, qty, price)
        if not ok:
            self.log.warning(f"Order blocked by risk engine: {reason}")
            return

        # Place order
        try:
            order = await self.broker.place_order(
                symbol=symbol,
                side=action,
                qty=qty,
                strategy_name=self.name
            )
            self.log.info(f"Order placed: {action.upper()} {qty}x {symbol} | Reason: {signal.get('reason', '')}")
        except Exception as e:
            self.log.error(f"Order failed for {symbol}: {e}")
