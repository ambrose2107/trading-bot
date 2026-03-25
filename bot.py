import asyncio
from datetime import datetime, timezone
from sqlalchemy import select

from core.logger import get_logger
from core.risk_engine import risk_engine
from core.database import AsyncSessionLocal, BotStatus
from brokers.alpaca_adapter import alpaca_broker

from strategies.stocks.ma_crossover import MovingAverageCrossover
from strategies.stocks.rsi_strategy import RSIStrategy

log = get_logger("bot")


# UTC helper
def utc_now():
    return datetime.now(timezone.utc)


class TradingBot:
    def __init__(self):
        self.running = False
        self.strategies = []
        self._setup_strategies()

    # Load strategies
    def _setup_strategies(self):
        self.strategies = [
            MovingAverageCrossover(alpaca_broker),
            RSIStrategy(alpaca_broker),
        ]

        log.info(
            f"Loaded {len(self.strategies)} strategies: "
            f"{[s.name for s in self.strategies]}"
        )

    # Start bot
    async def start(self):
        if self.running:
            log.info("Bot already running")
            return

        self.running = True
        log.info("Trading bot started")

        # Immediately update status
        await self._update_status(True, "Bot started")

        # Reset risk engine
        try:
            account = alpaca_broker.get_account()
            risk_engine.reset_daily(account.get("equity", 0))
        except Exception as e:
            log.error(f"Account fetch failed: {e}")

        await self._run_loop()

    # Stop bot
    async def stop(self):
        if not self.running:
            return

        self.running = False
        log.info("Trading bot stopped")
        await self._update_status(False, "Bot stopped")

    # Main loop
    async def _run_loop(self):
        while self.running:
            try:
                await self._cycle()

                # Heartbeat
                await self._update_status(True, "Bot running - heartbeat")

            except Exception as e:
                log.error(f"Cycle error: {e}")

            # Wait 5 minutes
            await asyncio.sleep(300)

    # Single cycle
    async def _cycle(self):
        if not alpaca_broker.is_market_open():
            log.info("Market closed — skipping cycle")
            return

        if getattr(risk_engine, "_kill_switch", False):
            log.warning("Kill switch active — skipping cycle")
            return

        log.info("Running strategies...")

        for strategy in self.strategies:
            try:
                await strategy.run()
            except Exception as e:
                log.error(f"{strategy.name} failed: {e}")

    # Update DB status
    async def _update_status(self, running: bool, message: str):
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(BotStatus).limit(1))
                status = result.scalar_one_or_none()

                # Create row if missing
                if not status:
                    status = BotStatus(
                        is_running=running,
                        message=message,
                        mode=alpaca_broker.mode,
                        started_at=utc_now(),
                        updated_at=utc_now(),
                    )
                    db.add(status)
                else:
                    status.is_running = running
                    status.message = message
                    status.mode = alpaca_broker.mode
                    status.updated_at = utc_now()

                    if running and not status.started_at:
                        status.started_at = utc_now()

                await db.commit()

                log.info(f"Status updated: {message}")

        except Exception as e:
            log.error(f"Status update failed: {e}")


# Global bot instance
bot = TradingBot()
