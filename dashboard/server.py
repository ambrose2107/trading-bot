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
    import numpy as np

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
            df["ts"] = (
                df[ts_col].astype(str).str[:16].str.replace("T", " ")
                if intraday
                else df[ts_col].astype(str).str[:10]
            )
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col])
        df["volume"] = pd.to_numeric(df["volume"]) if "volume" in df.columns else 0
        n = len(df)

        def safe_ma(p):
            if n < p:
                return [None] * n
            return [
                round(v, 2) if (v == v and v is not None) else None
                for v in df["close"].rolling(p).mean().tolist()
            ]

        def safe_ema(p):
            if n < p:
                return [None] * n
            return [
                round(v, 2) if (v == v and v is not None) else None
                for v in df["close"].ewm(span=p, adjust=False).mean().tolist()
            ]

        # RSI
        rsi_vals = [None] * n
        if n >= 15:
            delta = df["close"].diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, float("nan"))
            rsi_s = 100 - (100 / (1 + rs))
            rsi_vals = [
                round(v, 2) if (v == v and v is not None) else None
                for v in rsi_s.tolist()
            ]

        # MACD (12,26,9) - manual, no external lib
        macd_line = [None] * n
        macd_signal = [None] * n
        macd_hist = [None] * n
        if n >= 27:
            ema12 = df["close"].ewm(span=12, adjust=False).mean()
            ema26 = df["close"].ewm(span=26, adjust=False).mean()
            ml = ema12 - ema26
            ms = ml.ewm(span=9, adjust=False).mean()
            mh = ml - ms

            def clean(series):
                return [
                    round(v, 4) if (v == v and v is not None) else None
                    for v in series.tolist()
                ]

            macd_line = clean(ml)
            macd_signal = clean(ms)
            macd_hist = clean(mh)

        # Supertrend
        st_vals = [None] * n
        st_dir = [None] * n
        if n >= 11:
            hl2 = (df["high"] + df["low"]) / 2
            tr = pd.concat(
                [
                    df["high"] - df["low"],
                    abs(df["high"] - df["close"].shift(1)),
                    abs(df["low"] - df["close"].shift(1)),
                ],
                axis=1,
            ).max(axis=1)
            atr = tr.rolling(10).mean()
            ub = (hl2 + 3.0 * atr).tolist()
            lb = (hl2 - 3.0 * atr).tolist()
            cl = df["close"].tolist()
            direction = [1] * n
            for i in range(1, n):
                if lb[i] is None:
                    continue
                if cl[i] > (ub[i - 1] or 0):
                    direction[i] = 1
                elif cl[i] < (lb[i - 1] or 0):
                    direction[i] = -1
                else:
                    direction[i] = direction[i - 1]
                    if direction[i] == 1 and lb[i] < lb[i - 1]:
                        lb[i] = lb[i - 1]
                    if direction[i] == -1 and ub[i] > ub[i - 1]:
                        ub[i] = ub[i - 1]
                st_vals[i] = round(lb[i] if direction[i] == 1 else ub[i], 2)
                st_dir[i] = direction[i]

        vol_vals = df["volume"].round(0).tolist()

        return {
            "dates": df["ts"].tolist(),
            "close": df["close"].round(2).tolist(),
            "open": df["open"].round(2).tolist(),
            "high": df["high"].round(2).tolist(),
            "low": df["low"].round(2).tolist(),
            "volume": vol_vals,
            "ma21": safe_ma(21),
            "ma50": safe_ma(50),
            "ma200": safe_ma(200),
            "ema9": safe_ema(9),
            "ema21": safe_ema(21),
            "rsi": rsi_vals,
            "macd": macd_line,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "supertrend": st_vals,
            "st_dir": st_dir,
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
        strat = req.strategy
        if strat in ("ma_crossover", "both"):
            bt = Backtester(req.symbol, req.days, req.cash)
            r = bt.run_ma_crossover(req.fast_ma, req.slow_ma)
            r["strategy"] = "MA Crossover"
            r["equity_curve"] = bt.equity_curve
            r["trades"] = bt.trades
            results.append(r)
        if strat in ("rsi_strategy", "rsi", "both"):
            bt2 = Backtester(req.symbol, req.days, req.cash)
            r2 = bt2.run_rsi(req.rsi_period, req.oversold, req.overbought)
            r2["strategy"] = "RSI"
            r2["equity_curve"] = bt2.equity_curve
            r2["trades"] = bt2.trades
            results.append(r2)
        if strat == "macd_strategy":
            bt3 = Backtester(req.symbol, req.days, req.cash)
            r3 = bt3.run_macd()
            r3["strategy"] = "MACD"
            r3["equity_curve"] = bt3.equity_curve
            r3["trades"] = bt3.trades
            results.append(r3)
        if strat == "supertrend":
            bt4 = Backtester(req.symbol, req.days, req.cash)
            r4 = bt4.run_supertrend()
            r4["strategy"] = "Supertrend"
            r4["equity_curve"] = bt4.equity_curve
            r4["trades"] = bt4.trades
            results.append(r4)
        if not results:
            raise ValueError(f"Unknown strategy: {strat}")
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


@app.post("/api/backtest/multi")
async def run_multi_backtest(req: BacktestRequest):
    """Run all strategies on the same symbol and return comparison data."""
    try:
        results = []
        runs = [
            (
                "MA Crossover",
                lambda: Backtester(req.symbol, req.days, req.cash).run_ma_crossover(
                    req.fast_ma, req.slow_ma
                ),
            ),
            (
                "RSI",
                lambda: Backtester(req.symbol, req.days, req.cash).run_rsi(
                    req.rsi_period, req.oversold, req.overbought
                ),
            ),
            ("MACD", lambda: Backtester(req.symbol, req.days, req.cash).run_macd()),
            (
                "Supertrend",
                lambda: Backtester(req.symbol, req.days, req.cash).run_supertrend(),
            ),
        ]
        for name, fn in runs:
            try:
                bt = Backtester(req.symbol, req.days, req.cash)
                if name == "MA Crossover":
                    r = bt.run_ma_crossover(req.fast_ma, req.slow_ma)
                elif name == "RSI":
                    r = bt.run_rsi(req.rsi_period, req.oversold, req.overbought)
                elif name == "MACD":
                    r = bt.run_macd()
                else:
                    r = bt.run_supertrend()
                r["strategy"] = name
                r["equity_curve"] = bt.equity_curve
                r["trades"] = bt.trades
                results.append(r)
            except Exception as e:
                results.append(
                    {
                        "strategy": name,
                        "error": str(e),
                        "total_return_pct": 0,
                        "win_rate_pct": 0,
                        "total_trades": 0,
                        "equity_curve": [],
                        "trades": [],
                    }
                )
        return {"status": "ok", "results": results}
    except Exception as e:
        raise HTTPException(500, f"Multi-backtest error: {str(e)}")


# ── Watchlist ──────────────────────────────────────────────────────
@app.get("/api/watchlist")
async def get_watchlist(
    symbols: str = "AAPL,MSFT,NVDA,TSLA,SPY", days: int = 60, timeframe: str = "1Day"
):
    import pandas as pd

    results = {}
    sym_list = [x.strip().upper() for x in symbols.split(",")][:8]
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
            start = (datetime.now() - timedelta(days=days + 50)).strftime("%Y-%m-%d")
            df = alpaca_broker.api.get_bars(sym, tf, start=start, limit=days + 50).df
            df = df.reset_index()
            df.columns = [str(c).lower() for c in df.columns]
            ts_col = next((c for c in df.columns if "time" in c), None)
            if ts_col:
                df["ts"] = df[ts_col].astype(str).str[:10]
            df["close"] = pd.to_numeric(df["close"])
            df["open"] = (
                pd.to_numeric(df["open"]) if "open" in df.columns else df["close"]
            )
            df["high"] = (
                pd.to_numeric(df["high"]) if "high" in df.columns else df["close"]
            )
            df["low"] = pd.to_numeric(df["low"]) if "low" in df.columns else df["close"]
            df["volume"] = pd.to_numeric(df["volume"]) if "volume" in df.columns else 0
            cl = df["close"].round(2).tolist()
            last = cl[-1] if cl else 0
            first = cl[0] if cl else 0
            chg = round((last - first) / first * 100, 2) if first else 0
            ma50 = (
                [
                    round(v, 2) if v == v else None
                    for v in df["close"].rolling(50).mean().tolist()
                ]
                if len(df) >= 50
                else [None] * len(df)
            )
            results[sym] = {
                "dates": df["ts"].tolist(),
                "close": cl,
                "open": df["open"].round(2).tolist(),
                "high": df["high"].round(2).tolist(),
                "low": df["low"].round(2).tolist(),
                "volume": df["volume"].round(0).tolist(),
                "last": last,
                "chg_pct": chg,
                "ma50": ma50,
            }
        except Exception as e:
            results[sym] = {
                "error": str(e),
                "last": 0,
                "chg_pct": 0,
                "dates": [],
                "close": [],
                "volume": [],
            }
    return results


@app.get("/api/quote/{symbol}")
async def get_quote(symbol: str):
    try:
        price = await alpaca_broker.get_latest_price(symbol)
        return {"symbol": symbol, "price": price}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/multi-chart")
async def multi_chart(
    symbols: str = "AAPL", timeframes: str = "1D,1D,1D,1D", days: int = 180
):
    """Returns chart data for up to 4 symbol+timeframe combinations for multi-study panel."""
    import pandas as pd

    sym_list = [x.strip().upper() for x in symbols.split(",")]
    tf_list = [x.strip() for x in timeframes.split(",")]
    tf_map = {
        "5min": "5Min",
        "15min": "15Min",
        "1hr": "1Hour",
        "4hr": "4Hour",
        "1D": "1Day",
        "1W": "1Week",
    }
    results = []
    for i in range(min(4, len(sym_list))):
        sym = sym_list[i] if i < len(sym_list) else sym_list[0]
        tf = tf_map.get(tf_list[i] if i < len(tf_list) else "1D", "1Day")
        try:
            start = (datetime.now() - timedelta(days=days + 300)).strftime("%Y-%m-%d")
            df = alpaca_broker.api.get_bars(sym, tf, start=start, limit=days + 300).df
            df = df.reset_index()
            df.columns = [str(c).lower() for c in df.columns]
            ts_col = next((c for c in df.columns if "time" in c), None)
            if ts_col:
                df["ts"] = df[ts_col].astype(str).str[:10]
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col]) if col in df.columns else 0
            df["volume"] = pd.to_numeric(df["volume"]) if "volume" in df.columns else 0
            n = len(df)

            def sma(p):
                return (
                    [
                        round(v, 2) if v == v else None
                        for v in df["close"].rolling(p).mean().tolist()
                    ]
                    if n >= p
                    else [None] * n
                )

            def ema_fn(p):
                return [
                    round(v, 2) if v == v else None
                    for v in df["close"].ewm(span=p, adjust=False).mean().tolist()
                ]

            # RSI
            rsi = [None] * n
            if n >= 15:
                d = df["close"].diff()
                g = d.clip(lower=0).rolling(14).mean()
                l = (-d.clip(upper=0)).rolling(14).mean()
                rs = g / l.replace(0, float("nan"))
                r = 100 - (100 / (1 + rs))
                rsi = [round(v, 2) if v == v else None for v in r.tolist()]
            # MACD
            ml = ms = mh = [None] * n
            if n >= 27:
                e12 = df["close"].ewm(span=12, adjust=False).mean()
                e26 = df["close"].ewm(span=26, adjust=False).mean()
                _ml = e12 - e26
                _ms = _ml.ewm(span=9, adjust=False).mean()
                _mh = _ml - _ms
                clean = lambda s: [round(v, 4) if v == v else None for v in s.tolist()]
                ml, ms, mh = clean(_ml), clean(_ms), clean(_mh)
            results.append(
                {
                    "symbol": sym,
                    "timeframe": tf_list[i] if i < len(tf_list) else "1D",
                    "dates": df["ts"].tolist(),
                    "close": df["close"].round(2).tolist(),
                    "open": df["open"].round(2).tolist(),
                    "high": df["high"].round(2).tolist(),
                    "low": df["low"].round(2).tolist(),
                    "volume": df["volume"].round(0).tolist(),
                    "ma50": sma(50),
                    "ma200": sma(200),
                    "ema9": ema_fn(9),
                    "ema21": ema_fn(21),
                    "rsi": rsi,
                    "macd": ml,
                    "macd_signal": ms,
                    "macd_hist": mh,
                }
            )
        except Exception as e:
            results.append({"symbol": sym, "error": str(e), "dates": [], "close": []})
    return {"charts": results}


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
