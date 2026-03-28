import alpaca_trade_api as tradeapi
from core.config import config
from core.logger import get_logger
from core.database import AsyncSessionLocal, Trade
from datetime import datetime

log = get_logger("broker.alpaca")


class AlpacaBroker:
    """
    Adapter for Alpaca Markets.
    Swap this class out later for IBKR (options) or Binance (crypto)
    without touching any strategy code.
    """

    def __init__(self):
        self.api = tradeapi.REST(
            config.ALPACA_API_KEY,
            config.ALPACA_SECRET_KEY,
            config.ALPACA_BASE_URL,
            api_version="v2",
        )
        self.mode = config.ALPACA_MODE
        log.info(f"Alpaca broker initialised in {self.mode.upper()} mode")

    # ------------------------------------------------------------------
    # Account info
    # ------------------------------------------------------------------
    def get_account(self) -> dict:
        acct = self.api.get_account()
        return {
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value),
            "status": acct.status,
        }

    def get_positions(self) -> list[dict]:
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

    def is_market_open(self) -> bool:
        clock = self.api.get_clock()
        return clock.is_open

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------
    async def get_latest_price(self, symbol: str) -> float:
        bar = self.api.get_latest_bar(symbol)
        return float(bar.c)

    def get_bars(
        self, symbol: str, timeframe: str = "1Day", limit: int = 365
    ) -> list[dict]:
        """Get historical OHLCV bars using start date (more reliable than limit= on free tier)."""
        from datetime import datetime, timedelta
        import pandas as pd

        # Calculate start date from limit (limit = number of trading days approximately)
        calendar_days = int(limit * 1.5) + 60  # trading days to calendar days
        start = (datetime.now() - timedelta(days=calendar_days)).strftime("%Y-%m-%d")
        bars = self.api.get_bars(symbol, timeframe, start=start, limit=limit + 100).df
        bars = bars.reset_index()
        bars.columns = [str(c).lower() for c in bars.columns]
        # Keep only last `limit` rows
        bars = bars.tail(limit).reset_index(drop=True)
        return bars.to_dict("records")

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------
    async def place_order(
        self, symbol: str, side: str, qty: int, strategy_name: str = ""
    ) -> dict:
        log.info(f"Placing {side.upper()} order: {qty}x {symbol}")

        order = self.api.submit_order(
            symbol=symbol, qty=qty, side=side, type="market", time_in_force="day"
        )

        price = await self.get_latest_price(symbol)

        # Save to DB
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

    def get_recent_orders(self, limit: int = 20) -> list[dict]:
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


# Singleton
alpaca_broker = AlpacaBroker()
