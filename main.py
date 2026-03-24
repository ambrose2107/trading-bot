import asyncio
import uvicorn

from dashboard.server import app
from bot import TradingBot  # adjust if path differs

# ✅ CORRECT
from brokers.alpaca_adapter import AlpacaBroker

bot = None


async def start_bot():
    global bot
    broker = AlpacaBroker()
    bot = TradingBot()
    await bot.start()


async def main():
    # Start bot in background
    # asyncio.create_task(start_bot())

    # Start FastAPI server
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
