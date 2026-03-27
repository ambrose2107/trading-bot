import asyncio
import os
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime, timedelta
from pydantic import BaseModel

from core.database import init_db, get_db, Trade, BotStatus
from core.risk_engine import risk_engine
from core.logger import get_logger
from core.strategy_loader import get_strategy_info
from brokers.alpaca_adapter import alpaca_broker
from bot import bot
from backtest import Backtester

log = get_logger("dashboard")

app = FastAPI(title="Trading Bot", version="2.0.0")

# Only mount static if directory exists
if os.path.exists("dashboard/static"):
    app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")


@app.on_event("startup")
async def startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    await init_db()
    log.info("=" * 50)
    log.info("Dashboard started")
    # Test Alpaca connection
    try:
        acc = alpaca_broker.get_account()
        log.info(
            f"✓ Alpaca connected | equity=${acc['equity']} | mode={alpaca_broker.mode}"
        )
    except Exception as e:
        log.error(f"✗ Alpaca connection FAILED: {e}")
    # Test strategy loader
    try:
        from core.strategy_loader import get_strategy_info

        strats = get_strategy_info()
        log.info(f"✓ Strategies loaded: {[s['name'] for s in strats]}")
    except Exception as e:
        log.error(f"✗ Strategy loader FAILED: {e}")
    log.info("=" * 50)


# ── HTML ──────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    with open("dashboard/index.html") as f:
        content = f.read()
    response = HTMLResponse(content=content)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


# ── Account / Positions ───────────────────────────────────────────
@app.get("/api/account")
async def get_account():
    try:
        return alpaca_broker.get_account()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/positions")
async def get_positions():
    try:
        return alpaca_broker.get_positions()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/trades")
async def get_trades(limit: int = 50, db: AsyncSession = Depends(get_db)):
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
    result = await db.execute(select(BotStatus).limit(1))
    status = result.scalar_one_or_none()
    account = {}
    try:
        account = alpaca_broker.get_account()
    except:
        pass
    return {
        "is_running": status.is_running if status else False,
        "kill_switch": getattr(risk_engine, "_kill_switch", False),
        "mode": alpaca_broker.mode,
        "message": status.message if status else "Stopped",
        "started_at": str(status.started_at) if status and status.started_at else None,
        "equity": account.get("equity", 0),
        "daily_pnl": risk_engine.daily_pnl,
        "open_positions": len(alpaca_broker.get_positions()) if account else 0,
    }


# ── Bot controls ──────────────────────────────────────────────────
@app.post("/api/bot/start")
async def start_bot():
    if bot.running:
        return {"message": "Bot already running"}
    asyncio.create_task(bot.start())
    return {"message": "Bot started"}


@app.post("/api/bot/stop")
async def stop_bot():
    await bot.stop()
    return {"message": "Bot stopped"}


@app.post("/api/bot/kill-switch/on")
async def kill_switch_on():
    risk_engine.activate_kill_switch()
    await alpaca_broker.cancel_all_orders()
    return {"message": "Kill switch activated"}


@app.post("/api/bot/kill-switch/off")
async def kill_switch_off():
    risk_engine.deactivate_kill_switch()
    return {"message": "Kill switch deactivated"}


@app.post("/api/bot/emergency-close")
async def emergency_close():
    risk_engine.activate_kill_switch()
    await alpaca_broker.cancel_all_orders()
    await alpaca_broker.close_all_positions()
    return {"message": "EMERGENCY: All positions closed"}


class StartSelectedRequest(BaseModel):
    strategies: list


@app.post("/api/bot/start-selected")
async def start_selected(req: StartSelectedRequest):
    if bot.running:
        await bot.stop()
        await asyncio.sleep(1)
    asyncio.create_task(bot.start(strategy_names=req.strategies))
    return {"message": f"Started: {', '.join(req.strategies)}"}


# ── Strategies ────────────────────────────────────────────────────
@app.get("/api/strategies")
async def list_strategies():
    try:
        return {"strategies": get_strategy_info()}
    except Exception as e:
        return {"strategies": [], "error": str(e)}


@app.post("/api/strategies/reload")
async def reload_strategies():
    names = bot.reload_strategies()
    return {"message": f"Reloaded {len(names)} strategies", "strategies": names}


# ── Chart ─────────────────────────────────────────────────────────
@app.get("/api/chart4/{symbol}")
async def get_chart(symbol: str, days: int = 365, timeframe: str = "1Day"):
    import pandas as pd
    import ta

    try:
        tf_map = {
            "5min": "5Min",
            "15min": "15Min",
            "1hr": "1Hour",
            "4hr": "4Hour",
            "1D": "1Day",
            "1W": "1Week",
            "5Min": "5Min",
            "15Min": "15Min",
            "1Hour": "1Hour",
            "4Hour": "4Hour",
            "1Day": "1Day",
            "1Week": "1Week",
        }
        tf = tf_map.get(timeframe, "1Day")
        intraday = tf in ["5Min", "15Min", "1Hour", "4Hour"]
        if intraday:
            days_back = min(days, 59)
            start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            lim = 2000
        else:
            days_back = days * 7 if tf == "1Week" else days
            start = (datetime.now() - timedelta(days=days_back + 300)).strftime(
                "%Y-%m-%d"
            )
            lim = days + 300
        df = alpaca_broker.api.get_bars(symbol, tf, start=start, limit=lim).df
        df = df.reset_index()
        df.columns = [str(c).lower() for c in df.columns]
        ts_col = next((c for c in df.columns if "time" in c), None)
        if ts_col:
            if intraday:
                df["ts"] = df[ts_col].astype(str).str[:16].str.replace("T", " ")
            else:
                df["ts"] = df[ts_col].astype(str).str[:10]
        df["close"] = pd.to_numeric(df["close"])
        df["open"] = pd.to_numeric(df["open"])
        df["high"] = pd.to_numeric(df["high"])
        df["low"] = pd.to_numeric(df["low"])
        n = len(df)

        def safe_ma(p):
            if n >= p:
                vals = df["close"].rolling(p).mean().tolist()
                return [round(v, 2) if v == v else None for v in vals]
            return [None] * n

        rsi_vals = [None] * n
        if n >= 14:
            rsi_series = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
            rsi_vals = [round(v, 2) if v == v else None for v in rsi_series.tolist()]
        return {
            "dates": df["ts"].tolist(),
            "close": df["close"].round(2).tolist(),
            "open": df["open"].round(2).tolist(),
            "high": df["high"].round(2).tolist(),
            "low": df["low"].round(2).tolist(),
            "ma21": safe_ma(21),
            "ma50": safe_ma(50),
            "ma200": safe_ma(200),
            "rsi": rsi_vals,
            "count": n,
        }
    except Exception as e:
        raise HTTPException(500, f"Chart error: {str(e)}")


# ── Backtest ──────────────────────────────────────────────────────
class BacktestRequest(BaseModel):
    symbol: str
    strategy: str = "both"
    days: int = 365
    cash: float = 10000
    fast_ma: int = 50
    slow_ma: int = 200
    rsi_period: int = 14
    oversold: int = 30
    overbought: int = 70


@app.post("/api/backtest/run")
async def run_backtest(req: BacktestRequest):
    try:
        results = []
        if req.strategy in ("ma_crossover", "both"):
            bt = Backtester(req.symbol, req.days, req.cash)
            r = bt.run_ma_crossover(req.fast_ma, req.slow_ma)
            r["strategy"] = "MA Crossover"
            r["equity_curve"] = bt.equity_curve
            r["trades"] = bt.trades
            results.append(r)
        if req.strategy in ("rsi", "rsi_strategy", "both"):
            bt2 = Backtester(req.symbol, req.days, req.cash)
            r2 = bt2.run_rsi(req.rsi_period, req.oversold, req.overbought)
            r2["strategy"] = "RSI"
            r2["equity_curve"] = bt2.equity_curve
            r2["trades"] = bt2.trades
            results.append(r2)
        return {"status": "ok", "results": results}
    except Exception as e:
        raise HTTPException(500, f"Backtest error: {str(e)}")


class StrategyBacktestRequest(BaseModel):
    symbol: str
    strategy: str
    days: int = 365
    cash: float = 10000
    fast_ma: int = 50
    slow_ma: int = 200
    rsi_period: int = 14
    oversold: int = 30
    overbought: int = 70
    ema_fast: int = 9
    ema_mid: int = 21
    ema_slow: int = 50
    risk_per_trade: float = 0.01


@app.post("/api/backtest/strategy")
async def backtest_strategy(req: StrategyBacktestRequest):
    try:
        import pandas as pd

        start = (datetime.now() - timedelta(days=req.days + 300)).strftime("%Y-%m-%d")
        df = alpaca_broker.api.get_bars(
            req.symbol, "1Day", start=start, limit=req.days + 300
        ).df
        df = df.reset_index()
        df.columns = [str(c).lower() for c in df.columns]
        ts_col = next((c for c in df.columns if "time" in c), None)
        if ts_col:
            df["timestamp"] = df[ts_col].astype(str).str[:10]
        df["close"] = pd.to_numeric(df["close"])
        df["open"] = pd.to_numeric(df["open"])
        df["high"] = pd.to_numeric(df["high"])
        df["low"] = pd.to_numeric(df["low"])

        if req.strategy == "institutional_ema":
            df["ema9"] = df["close"].ewm(span=9).mean()
            df["ema21"] = df["close"].ewm(span=21).mean()
            df["ema50"] = df["close"].ewm(span=50).mean()
            df["ema200"] = df["close"].ewm(span=200).mean()
            df["tr1"] = df["high"] - df["low"]
            df["tr2"] = abs(df["high"] - df["close"].shift())
            df["tr3"] = abs(df["low"] - df["close"].shift())
            df["atr"] = df[["tr1", "tr2", "tr3"]].max(axis=1).rolling(14).mean()
            df = df.dropna().reset_index(drop=True)
            cash = req.cash
            shares = 0
            trades = []
            equity_curve = []
            entry_price = 0
            for i in range(1, len(df)):
                row = df.iloc[i]
                prev = df.iloc[i - 1]
                price = row["close"]
                ts = row["timestamp"]
                bull = price > row["ema200"] and row["ema50"] > row["ema200"]
                pb = abs(price - row["ema21"]) / price < 0.015
                bcross = prev["ema9"] < prev["ema21"] and row["ema9"] > row["ema21"]
                vvol = row["atr"] / price > 0.01
                bear = prev["ema9"] > prev["ema21"] and row["ema9"] < row["ema21"]
                tbrk = price < row["ema200"]
                if bull and pb and bcross and vvol and shares == 0:
                    rps = 1.5 * row["atr"]
                    qty = int((cash * req.risk_per_trade) / rps) if rps > 0 else 0
                    qty = min(qty, int(cash * 0.95 / price))
                    if qty > 0:
                        cash -= qty * price
                        shares = qty
                        entry_price = price
                        trades.append(
                            {
                                "date": ts,
                                "side": "BUY",
                                "qty": qty,
                                "price": round(price, 2),
                                "reason": "EMA setup",
                                "value": qty * price,
                            }
                        )
                elif shares > 0 and (
                    bear or tbrk or price < entry_price - 1.5 * row["atr"]
                ):
                    pnl = (price - entry_price) * shares
                    cash += shares * price
                    trades.append(
                        {
                            "date": ts,
                            "side": "SELL",
                            "qty": shares,
                            "price": round(price, 2),
                            "reason": "Exit signal",
                            "pnl": round(pnl, 2),
                            "value": shares * price,
                        }
                    )
                    shares = 0
                equity_curve.append(
                    {"date": ts, "equity": round(cash + shares * price, 2)}
                )
            final = cash + shares * (df["close"].iloc[-1] if shares > 0 else 0)
            sells = [t for t in trades if t["side"] == "SELL"]
            wins = [t for t in sells if t.get("pnl", 0) > 0]
            return {
                "status": "ok",
                "results": [
                    {
                        "strategy": "Institutional EMA",
                        "symbol": req.symbol,
                        "starting_cash": req.cash,
                        "final_equity": round(final, 2),
                        "total_return_pct": round(
                            (final - req.cash) / req.cash * 100, 2
                        ),
                        "total_pnl": round(sum(t.get("pnl", 0) for t in sells), 2),
                        "total_trades": len(trades),
                        "winning_trades": len(wins),
                        "losing_trades": len(sells) - len(wins),
                        "win_rate_pct": round(len(wins) / len(sells) * 100, 2)
                        if sells
                        else 0,
                        "equity_curve": equity_curve,
                        "trades": trades,
                    }
                ],
            }
        else:
            bt = Backtester(req.symbol, req.days, req.cash)
            if req.strategy == "ma_crossover":
                r = bt.run_ma_crossover(req.fast_ma, req.slow_ma)
                r["strategy"] = "MA Crossover"
            else:
                r = bt.run_rsi(req.rsi_period, req.oversold, req.overbought)
                r["strategy"] = "RSI"
            r["equity_curve"] = bt.equity_curve
            r["trades"] = bt.trades
            return {"status": "ok", "results": [r]}
    except Exception as e:
        raise HTTPException(500, f"Strategy backtest error: {str(e)}")


# ── Multi-stock watchlist ─────────────────────────────
@app.get("/api/watchlist")
async def get_watchlist(
    symbols: str = "AAPL,MSFT,NVDA,TSLA,SPY", days: int = 30, timeframe: str = "1Day"
):
    """Get chart data for multiple symbols at once for the live watchlist."""
    import pandas as pd

    results = {}
    sym_list = [s.strip().upper() for s in symbols.split(",")][:8]  # max 8
    tf_map = {
        "5min": "5Min",
        "15min": "15Min",
        "1hr": "1Hour",
        "4hr": "4Hour",
        "1D": "1Day",
        "1W": "1Week",
    }
    tf = tf_map.get(timeframe, "1Day")
    for sym in sym_list:
        try:
            start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y-%m-%d")
            df = alpaca_broker.api.get_bars(sym, tf, start=start, limit=days + 10).df
            df = df.reset_index()
            df.columns = [str(c).lower() for c in df.columns]
            ts_col = next((c for c in df.columns if "time" in c), None)
            if ts_col:
                df["ts"] = df[ts_col].astype(str).str[:10]
            df["close"] = pd.to_numeric(df["close"])
            cl = df["close"].round(2).tolist()
            last = cl[-1] if cl else 0
            first = cl[0] if cl else 0
            chg_pct = round((last - first) / first * 100, 2) if first else 0
            results[sym] = {
                "dates": df["ts"].tolist(),
                "close": cl,
                "open": pd.to_numeric(df["open"]).round(2).tolist()
                if "open" in df.columns
                else [],
                "high": pd.to_numeric(df["high"]).round(2).tolist()
                if "high" in df.columns
                else [],
                "low": pd.to_numeric(df["low"]).round(2).tolist()
                if "low" in df.columns
                else [],
                "volume": df["volume"].round(0).tolist()
                if "volume" in df.columns
                else [],
                "last": last,
                "chg_pct": chg_pct,
                "ma50": df["close"].rolling(50).mean().round(2).tolist()
                if len(df) >= 50
                else [None] * len(df),
            }
        except Exception as e:
            results[sym] = {
                "error": str(e),
                "last": 0,
                "chg_pct": 0,
                "dates": [],
                "close": [],
            }
    return results


@app.get("/api/quote/{symbol}")
async def get_quote(symbol: str):
    """Get latest price for a symbol."""
    try:
        price = await alpaca_broker.get_latest_price(symbol)
        return {"symbol": symbol, "price": price}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Health & Debug ────────────────────────────────────
@app.get("/api/health")
async def health():
    """Quick health check - use this to verify server is alive"""
    import os

    return {
        "status": "ok",
        "version": "2.1",
        "alpaca_key_set": bool(
            os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        ),
        "mode": alpaca_broker.mode,
        "endpoints": [
            "/api/status",
            "/api/account",
            "/api/positions",
            "/api/strategies",
            "/api/chart4/{symbol}",
            "/api/backtest/run",
            "/api/backtest/strategy",
        ],
    }


@app.get("/api/debug")
async def debug():
    """Full debug info - check this when something is wrong"""
    import os, sys

    checks = {}
    try:
        acc = alpaca_broker.get_account()
        checks["alpaca"] = f"OK equity={acc['equity']}"
    except Exception as e:
        checks["alpaca"] = f"FAIL: {str(e)}"

    try:
        from core.strategy_loader import get_strategy_info

        strats = get_strategy_info()
        checks["strategies"] = f"OK found {len(strats)}: {[s['name'] for s in strats]}"
    except Exception as e:
        checks["strategies"] = f"FAIL: {str(e)}"

    checks["bot_running"] = bot.running
    checks["kill_switch"] = getattr(risk_engine, "_kill_switch", False)
    checks["python"] = sys.version
    checks["env_keys"] = {
        "ALPACA_API_KEY": bool(os.getenv("ALPACA_API_KEY")),
        "APCA_API_KEY_ID": bool(os.getenv("APCA_API_KEY_ID")),
        "ALPACA_SECRET_KEY": bool(os.getenv("ALPACA_SECRET_KEY")),
        "APCA_API_SECRET_KEY": bool(os.getenv("APCA_API_SECRET_KEY")),
        "ALPACA_MODE": os.getenv("ALPACA_MODE", "not set"),
    }
    return checks
