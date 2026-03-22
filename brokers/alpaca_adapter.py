import alpaca_trade_api as tradeapi
from datetime import datetime, timedelta
from core.config import config
from core.logger import get_logger
from core.database import AsyncSessionLocal, Trade

log = get_logger("broker.alpaca")


class AlpacaBroker:
    def __init__(self):





        self.api = tradeapi.REST(
            config.ALPACA_API_KEY,
            config.ALPACA_SECRET_KEY,
            config.ALPACA_BASE_URL,
            api_version="v2",
        )
        self.mode = config.ALPACA_MODE
        log.info(f"Alpaca broker initialised in {self.mode.upper()} mode")

    def get_account(self):
        acct = self.api.get_account()
        return {
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value),
            "status": acct.status,
        }

    def get_positions(self):
        positions = self.api.list_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pnl": float(p.unrealized_pl),
                "unrealized_pct": float(p.unrealized_plpc),
            }
            for p in positions
        ]

    def is_market_open(self):
        return self.api.get_clock().is_open

    async def get_latest_price(self, symbol):
        bar = self.api.get_latest_bar(symbol)
        return float(bar.c)

    def get_bars(self, symbol, timeframe="1Day", limit=365):
        tf_map = {"1D": "1Day", "1W": "1Week", "1Day": "1Day", "1Week": "1Week"}
        tf = tf_map.get(timeframe, "1Day")
        # Use date range — much more reliable than limit alone
        days_map = {"1Day": limit, "1Week": limit * 7}
        days_back = days_map.get(tf, limit) + 300
        start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        df = self.api.get_bars(symbol, tf, start=start, limit=limit + 300).df
        # timestamp is the index — reset it to become a column
        df = df.reset_index()
        df = df.rename(columns={"index": "timestamp"})
        # Ensure timestamp column exists and is named correctly
        if "timestamp" not in df.columns:
            df["timestamp"] = df.index
        df["timestamp"] = df["timestamp"].astype(str).str[:10]
        # Keep only needed columns
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                import pandas as pd

                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.to_dict("records")

    async def place_order(self, symbol, side, qty, strategy_name=""):
        log.info(f"Placing {side.upper()} order: {qty}x {symbol}")
        order = self.api.submit_order(
            symbol=symbol, qty=qty, side=side, type="market", time_in_force="day"
        )
        price = await self.get_latest_price(symbol)
        async with AsyncSessionLocal() as db:
            trade = Trade(
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                total_value=qty * price,
                strategy=strategy_name,
                asset_class="stock",
                order_id=order.id,
                status=order.status,
            )
            db.add(trade)
            await db.commit()
        log.info(f"Order submitted: {order.id} | Status: {order.status}")
        return {"order_id": order.id, "status": order.status}

    async def cancel_all_orders(self):
        self.api.cancel_all_orders()
        log.warning("All open orders cancelled")

    async def close_all_positions(self):
        self.api.close_all_positions()
        log.warning("All positions closed (EMERGENCY)")

    def get_recent_orders(self, limit=20):
        orders = self.api.list_orders(status="all", limit=limit)
        return [
            {
                "id": o.id,
                "symbol": o.symbol,
                "side": o.side,
                "qty": float(o.qty),
                "status": o.status,
                "filled_at": str(o.filled_at),
                "filled_avg_price": float(o.filled_avg_price)
                if o.filled_avg_price
                else None,
            }
            for o in orders
        ]


alpaca_broker = AlpacaBroker()
