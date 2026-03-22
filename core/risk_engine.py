from core.config import config
from core.logger import get_logger

log = get_logger("risk")


class RiskEngine:
    """
    Guards every order before it reaches the broker.
    All strategies MUST call check_order() before placing trades.
    """

    def __init__(self):
        self.daily_pnl       = 0.0
        self.starting_equity = 0.0
        self.open_positions  = 0

    def reset_daily(self, equity: float):
        self.daily_pnl       = 0.0
        self.starting_equity = equity
        log.info(f"Risk engine reset. Starting equity: ${equity:,.2f}")

    def update_pnl(self, pnl_change: float):
        self.daily_pnl += pnl_change

    def set_open_positions(self, count: int):
        self.open_positions = count

    # ------------------------------------------------------------------
    # Core check — call before EVERY order
    # ------------------------------------------------------------------
    def check_order(self, symbol: str, side: str, qty: float, price: float) -> tuple[bool, str]:
        order_value = qty * price

        # 1. Kill switch
        if getattr(self, "_kill_switch", False):
            return False, "KILL SWITCH is active. No orders allowed."

        # 2. Daily loss limit
        if self.starting_equity > 0:
            daily_loss_pct = abs(self.daily_pnl) / self.starting_equity
            if self.daily_pnl < 0 and daily_loss_pct >= config.MAX_DAILY_LOSS_PCT:
                return False, f"Daily loss limit hit ({daily_loss_pct:.1%}). Bot paused for today."

        # 3. Max open positions (only blocks new buys)
        if side == "buy" and self.open_positions >= config.MAX_OPEN_POSITIONS:
            return False, f"Max open positions reached ({config.MAX_OPEN_POSITIONS})."

        # 4. Single order size limit
        if self.starting_equity > 0:
            order_pct = order_value / self.starting_equity
            if order_pct > 0.25:
                return False, f"Single order too large ({order_pct:.1%} of portfolio). Max 25%."

        log.info(f"Risk check PASSED: {side.upper()} {qty} {symbol} @ ${price:.2f} (${order_value:,.2f})")
        return True, "OK"

    def calculate_position_size(self, equity: float, price: float, risk_pct: float = None) -> int:
        """Returns the number of shares to buy based on risk % of portfolio."""
        risk_pct = risk_pct or config.MAX_PORTFOLIO_RISK_PCT
        dollar_risk = equity * risk_pct
        shares = int(dollar_risk / price)
        return max(1, shares)

    def activate_kill_switch(self):
        self._kill_switch = True
        log.warning("KILL SWITCH ACTIVATED. All trading halted.")

    def deactivate_kill_switch(self):
        self._kill_switch = False
        log.info("Kill switch deactivated. Trading resumed.")


# Singleton — import this everywhere
risk_engine = RiskEngine()
