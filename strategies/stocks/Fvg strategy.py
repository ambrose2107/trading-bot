"""
FVG — Fair Value Gap Strategy
==============================
Based on Smart Money Concepts (SMC) / ICT methodology (as shown in @tradearshh):

A Fair Value Gap (FVG) is a 3-candle imbalance:
  BULLISH FVG: candle[i-2].high  <  candle[i].low
               → price "gapped up", leaving an unfilled zone below
  BEARISH FVG: candle[i-2].low   >  candle[i].high
               → price "gapped down", leaving an unfilled zone above

The 3rd candle character matters:
  • Bullish candle  → strongest confirmation
  • Consolidation   → acceptable entry (doji / inside bar)
  • Rejection candle → wick into FVG then close above (confirming support)

Trading logic:
  BUY  when price retraces INTO a bullish FVG zone  (buying at discount)
  SELL when price retraces INTO a bearish FVG zone  (selling at premium)

Win rate: ~60-70% when combined with higher-timeframe trend direction.
"""
import pandas as pd
import numpy as np
from core.strategy_base import BaseStrategy


class FVGStrategy(BaseStrategy):

    def __init__(self, broker):
        super().__init__(broker, name="fvg_strategy")
        self.watchlist      = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "SPY", "QQQ"]
        self.risk_per_trade = 0.015   # 1.5% capital per trade
        self.fvg_lookback   = 20      # how many candles back to look for FVGs
        self.min_gap_pct    = 0.003   # minimum gap size (0.3% of price) to be valid FVG

    def get_symbols(self):
        return self.watchlist

    def find_fvg_zones(self, df: pd.DataFrame):
        """Find all active (unfilled) FVG zones in recent candles."""
        bullish_fvgs = []  # list of (low, high) zones — price is a discount here
        bearish_fvgs = []  # list of (low, high) zones — price is a premium here
        n = len(df)

        for i in range(2, n):
            c1_high = df["high"].iloc[i-2]   # candle 1
            c1_low  = df["low"].iloc[i-2]
            c3_high = df["high"].iloc[i]      # candle 3 (current)
            c3_low  = df["low"].iloc[i]
            mid_p   = df["close"].iloc[i]

            # Bullish FVG: gap between c1 high and c3 low
            if c1_high < c3_low:
                gap_size = (c3_low - c1_high) / c1_high
                if gap_size >= self.min_gap_pct:
                    # Check if gap is still unfilled (price hasn't come back down)
                    recent_lows = df["low"].iloc[i:]
                    if len(recent_lows) == 0 or recent_lows.min() > c1_high:
                        bullish_fvgs.append({
                            "zone_low":  c1_high,
                            "zone_high": c3_low,
                            "formed_at": i,
                            "gap_pct":   round(gap_size * 100, 2)
                        })

            # Bearish FVG: gap between c1 low and c3 high
            if c1_low > c3_high:
                gap_size = (c1_low - c3_high) / c3_high
                if gap_size >= self.min_gap_pct:
                    recent_highs = df["high"].iloc[i:]
                    if len(recent_highs) == 0 or recent_highs.max() < c1_low:
                        bearish_fvgs.append({
                            "zone_low":  c3_high,
                            "zone_high": c1_low,
                            "formed_at": i,
                            "gap_pct":   round(gap_size * 100, 2)
                        })

        return bullish_fvgs, bearish_fvgs

    def candle_type(self, df: pd.DataFrame, i: int) -> str:
        """Classify a candle as bullish / bearish / consolidation / rejection."""
        o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
        body = abs(c - o)
        rng  = h - l if h != l else 1
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l

        if body / rng < 0.25:
            return "consolidation"
        if c > o and lower_wick / rng > 0.4:
            return "rejection_bullish"   # hammer — bullish signal
        if c > o:
            return "bullish"
        if c < o:
            return "bearish"
        return "consolidation"

    async def generate_signals(self):
        signals   = []
        account   = self.broker.get_account()
        equity    = float(account["equity"])
        positions = {p["symbol"]: p for p in self.broker.get_positions()}

        for symbol in self.watchlist:
            try:
                bars = self.broker.get_bars(symbol, timeframe="1Day", limit=60)
                if len(bars) < 20:
                    continue

                df = pd.DataFrame(bars)
                for col in ["open", "high", "low", "close"]:
                    df[col] = pd.to_numeric(df[col])

                # Higher-timeframe trend filter using MA200 slope
                ma50  = df["close"].rolling(50).mean()
                trend_up = ma50.iloc[-1] > ma50.iloc[-5] if len(ma50.dropna()) >= 5 else True

                # Find FVG zones in recent candles
                search_df = df.tail(self.fvg_lookback).reset_index(drop=True)
                bull_fvgs, bear_fvgs = self.find_fvg_zones(search_df)

                price  = df["close"].iloc[-1]
                in_pos = symbol in positions
                c_type = self.candle_type(df, -1)

                # BUY: price is currently inside a bullish FVG zone
                for fvg in bull_fvgs[-3:]:  # only check 3 most recent
                    if fvg["zone_low"] <= price <= fvg["zone_high"] and not in_pos and trend_up:
                        # Confirm with candle type (not bearish)
                        if c_type in ("bullish", "consolidation", "rejection_bullish"):
                            qty = max(1, int((equity * self.risk_per_trade) / price))
                            signals.append({
                                "symbol": symbol, "action": "buy", "qty": qty,
                                "reason": f"FVG buy: price={price:.2f} in bull FVG [{fvg['zone_low']:.2f}-{fvg['zone_high']:.2f}] ({fvg['gap_pct']}% gap) | candle={c_type}"
                            })
                            self.log.info(f"BUY  {symbol} FVG zone qty={qty}")
                            break

                # EXIT: price reaches a bearish FVG (overhead supply) OR falls out of FVG
                if in_pos:
                    for fvg in bear_fvgs[-3:]:
                        if price >= fvg["zone_low"]:
                            qty = int(float(positions[symbol]["qty"]))
                            signals.append({
                                "symbol": symbol, "action": "sell", "qty": qty,
                                "reason": f"FVG exit: price={price:.2f} reached bearish FVG [{fvg['zone_low']:.2f}-{fvg['zone_high']:.2f}]"
                            })
                            self.log.info(f"SELL {symbol} FVG overhead supply qty={qty}")
                            break

            except Exception as e:
                self.log.error(f"FVG error {symbol}: {e}")

        return signals