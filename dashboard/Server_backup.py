import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
import os

from core.database import init_db, get_db, Trade, BotStatus
from core.risk_engine import risk_engine
from core.logger import get_logger
from brokers.alpaca_adapter import alpaca_broker
from bot import bot
from backtest import Backtester

from fastapi.middleware.cors import CORSMiddleware

log = get_logger("dashboard")


# ── SAFE BOT RUNNER (NON-BLOCKING) ───────────────────────────────
async def run_bot_safe():
    try:
        log.info("🚀 Bot starting...")
        await bot.start()
    except Exception as e:
        log.error(f"❌ Bot crashed: {e}")


# ── Lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🔥 Initializing DB...")
    await init_db()

    log.info("🚀 Launching bot task...")
    asyncio.create_task(run_bot_safe())

    yield

    log.info("🛑 Shutting down bot...")
    await bot.stop()


# ── App ─────────────────────────────────────────────────────────
app = FastAPI(title="Trading Bot Dashboard", version="1.0.0", lifespan=lifespan)


# ── Static Files ─────────────────────────────────────────────────
if os.path.isdir("dashboard/static"):
    app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")


# ── CORS (VERY IMPORTANT) ────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later restrict
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ───────────────────────────────────────────────────────
@app.get("/health")
async def health():
    log.info("📡 API HIT: /health")
    return {"status": "ok"}


# ── Dashboard ────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    log.info("📡 Serving dashboard HTML")
    with open("dashboard/index.html") as f:
        content = f.read()
    return HTMLResponse(content=content)


# ── API ──────────────────────────────────────────────────────────
@app.get("/api/account")
async def get_account():
    log.info("📡 /api/account")
    try:
        return alpaca_broker.get_account()
    except Exception as e:
        log.error(f"❌ Account error: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/positions")
async def get_positions():
    log.info("📡 /api/positions")
    try:
        return alpaca_broker.get_positions()
    except Exception as e:
        log.error(f"❌ Positions error: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/trades")
async def get_trades(limit: int = 50, db: AsyncSession = Depends(get_db)):
    log.info("📡 /api/trades")
    result = await db.execute(
        select(Trade).order_by(desc(Trade.created_at)).limit(limit)
    )
    trades = result.scalars().all()

    return [
        {
            "id": t.id,
            "symbol": t.symbol,
            "side": t.side,
            "qty": t.qty,
            "price": t.price,
            "total_value": t.total_value,
            "strategy": t.strategy,
            "status": t.status,
            "pnl": t.pnl,
            "created_at": str(t.created_at),
        }
        for t in trades
    ]


@app.get("/api/status")
async def get_status(db: AsyncSession = Depends(get_db)):
    log.info("📡 /api/status")

    result = await db.execute(select(BotStatus).limit(1))
    status = result.scalar_one_or_none()

    try:
        account = alpaca_broker.get_account()
        positions = alpaca_broker.get_positions()
    except Exception as e:
        log.error(f"❌ Status error: {e}")
        account, positions = {}, []

    return {
        "is_running": status.is_running if status else False,
        "kill_switch": getattr(risk_engine, "_kill_switch", False),
        "mode": alpaca_broker.mode,
        "message": status.message if status else "Unknown",
        "started_at": str(status.started_at) if status else None,
        "equity": account.get("equity", 0),
        "daily_pnl": risk_engine.daily_pnl,
        "open_positions": len(positions),
    }


# ── BOT CONTROL ──────────────────────────────────────────────────
@app.post("/api/bot/start")
async def start_bot():
    log.info("📡 /api/bot/start")

    if bot.running:
        return {"message": "Already running"}

    asyncio.create_task(run_bot_safe())
    return {"message": "Bot started"}


@app.post("/api/bot/stop")
async def stop_bot():
    log.info("📡 /api/bot/stop")

    await bot.stop()
    return {"message": "Bot stopped"}


@app.post("/api/bot/kill-switch/on")
async def kill_switch_on():
    log.warning("🚨 Kill switch ON")

    risk_engine.activate_kill_switch()
    await alpaca_broker.cancel_all_orders()

    return {"message": "Kill switch activated"}


@app.post("/api/bot/kill-switch/off")
async def kill_switch_off():
    log.info("✅ Kill switch OFF")

    risk_engine.deactivate_kill_switch()
    return {"message": "Kill switch off"}


@app.post("/api/bot/emergency-close")
async def emergency_close():
    log.error("🚨 EMERGENCY CLOSE")

    risk_engine.activate_kill_switch()
    await alpaca_broker.cancel_all_orders()
    await alpaca_broker.close_all_positions()

    return {"message": "Emergency close complete"}
