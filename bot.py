import asyncio
from datetime import datetime, timezone

from core.logger import get_logger
from core.risk_engine import risk_engine
from core.database import init_db, AsyncSessionLocal, BotStatus
from brokers.alpaca_adapter import alpaca_broker

from strategies.stocks.ma_crossover import MovingAverageCrossover
from strategies.stocks.rsi_strategy import RSIStrategy

from sqlalchemy import select

log = get_logger("bot")


# ✅ Helper (timezone-safe UTC)
def utc_now():
    return datetime.now(timezone.utc)


class TradingBot:
    def __init__(self):
        self.running = False
        self.strategies = []
        self._setup_strategies()

    def _setup_strategies(self):
        self.strategies = [
            MovingAverageCrossover(alpaca_broker),
            RSIStrategy(alpaca_broker),
        ]
        log.info(
            f"Loaded {len(self.strategies)} strategies: {[s.name for s in self.strategies]}"
        )

    async def start(self):
    
        self.running = True

        log.info("Trading bot started")

        # ✅ Set ONLINE immediately
        await self._update_status(True, "Bot is running")

        # Reset risk engine
        try:
            account = alpaca_broker.get_account()
            risk_engine.reset_daily(account["equity"])
        except Exception as e:
            log.error(f"Could not fetch account on start: {e}")

        await self._run_loop()

    async def stop(self):
        self.running = False
        log.info("Trading bot stopped")
        await self._update_status(False, "Bot stopped by user")

    async def _run_loop(self):
        while self.running:
            try:
                await self._cycle()

                # ✅ HEARTBEAT (keeps dashboard ONLINE)
                await self._update_status(True, "Bot running - heartbeat")

            except Exception as e:
                log.error(f"Cycle error: {e}")

            # Run every 5 min
            await asyncio.sleep(300)

    async def _cycle(self):
        # Market check
        if not alpaca_broker.is_market_open():
            log.info("Market closed — skipping cycle")
            return

        # Kill switch check
        if getattr(risk_engine, "_kill_switch", False):
            log.warning("Kill switch active — skipping cycle")
            return

        log.info("--- Running cycle ---")

        for strategy in self.strategies:
            try:
                await strategy.run()
            except Exception as e:
                log.error(f"Strategy {strategy.name} error: {e}")

    async def _update_status(self, running: bool, message: str):
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(BotStatus).limit(1))
                status = result.scalar_one_or_none()

                if not status:
                    status = BotStatus()
                    db.add(status)

                status.is_running = running
                status.message = message
                status.mode = alpaca_broker.mode

                # ✅ FIXED (timezone-aware)
                status.updated_at = utc_now()

                if running and not status.started_at:
                    status.started_at = utc_now()

                await db.commit()

        except Exception as e:
            log.error(f"Could not update bot status: {e}")


# Global bot instance
bot = TradingBot()
