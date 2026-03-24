from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from datetime import datetime, timezone
from core.config import config

engine = create_async_engine(config.DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


# ✅ Helper for timezone-safe UTC
def utc_now():
    return datetime.now(timezone.utc)


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    side = Column(String)
    qty = Column(Float)
    price = Column(Float)
    total_value = Column(Float)
    strategy = Column(String)
    asset_class = Column(String, default="stock")
    order_id = Column(String, unique=True)
    status = Column(String)
    pnl = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, unique=True, index=True)
    qty = Column(Float)
    avg_entry = Column(Float)
    current_price = Column(Float)
    unrealized_pnl = Column(Float)
    strategy = Column(String)
    asset_class = Column(String, default="stock")
    opened_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class DailyStats(Base):
    __tablename__ = "daily_stats"
    id = Column(Integer, primary_key=True)
    date = Column(String, unique=True, index=True)
    starting_equity = Column(Float)
    ending_equity = Column(Float)
    realized_pnl = Column(Float)
    total_trades = Column(Integer)
    winning_trades = Column(Integer)
    losing_trades = Column(Integer)
    kill_switch_hit = Column(Boolean, default=False)


class BotStatus(Base):
    __tablename__ = "bot_status"

    id = Column(Integer, primary_key=True)
    is_running = Column(Boolean, default=False)
    kill_switch = Column(Boolean, default=False)
    mode = Column(String, default="paper")
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utc_now)  # ✅ FIXED
    message = Column(Text, default="Bot is stopped")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
