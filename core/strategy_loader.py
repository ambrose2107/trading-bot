"""
Strategy Loader
Discovers all strategy classes from strategies/stocks/
and returns metadata (display_name, description, params) for the UI.
"""

import os
import importlib
import inspect
from core.logger import get_logger

log = get_logger("strategy_loader")

# ── Metadata for all strategies (UI display + editable params) ───
STRATEGY_PARAMS = {
    "ma_crossover": {
        "display_name": "MA Crossover",
        "description": "Golden/death cross — MA50 vs MA200",
        "params": [
            {
                "key": "fast_period",
                "label": "Fast MA",
                "type": "number",
                "default": 50,
                "min": 5,
                "max": 199,
            },
            {
                "key": "slow_period",
                "label": "Slow MA",
                "type": "number",
                "default": 200,
                "min": 10,
                "max": 500,
            },
            {
                "key": "risk_per_trade",
                "label": "Risk %",
                "type": "number",
                "default": 0.015,
                "min": 0.005,
                "max": 0.05,
                "step": 0.005,
            },
        ],
    },
    "rsi_strategy": {
        "display_name": "RSI Mean Reversion",
        "description": "Buy oversold (<30), sell overbought (>70)",
        "params": [
            {
                "key": "rsi_period",
                "label": "RSI Period",
                "type": "number",
                "default": 14,
                "min": 5,
                "max": 30,
            },
            {
                "key": "oversold",
                "label": "Oversold",
                "type": "number",
                "default": 30,
                "min": 10,
                "max": 45,
            },
            {
                "key": "overbought",
                "label": "Overbought",
                "type": "number",
                "default": 70,
                "min": 55,
                "max": 90,
            },
            {
                "key": "risk_per_trade",
                "label": "Risk %",
                "type": "number",
                "default": 0.015,
                "min": 0.005,
                "max": 0.05,
                "step": 0.005,
            },
        ],
    },
    "institutional_ema": {
        "display_name": "Institutional EMA",
        "description": "EMA 9/21/50/200 stack with ATR sizing",
        "params": [
            {
                "key": "ema_fast",
                "label": "EMA Fast",
                "type": "number",
                "default": 9,
                "min": 3,
                "max": 20,
            },
            {
                "key": "ema_mid",
                "label": "EMA Mid",
                "type": "number",
                "default": 21,
                "min": 10,
                "max": 50,
            },
            {
                "key": "ema_slow",
                "label": "EMA Slow",
                "type": "number",
                "default": 50,
                "min": 20,
                "max": 100,
            },
            {
                "key": "risk_per_trade",
                "label": "Risk %",
                "type": "number",
                "default": 0.01,
                "min": 0.005,
                "max": 0.05,
                "step": 0.005,
            },
        ],
    },
    "macd_strategy": {
        "display_name": "MACD Crossover",
        "description": "Buy/sell on MACD × Signal line cross",
        "params": [
            {
                "key": "fast_period",
                "label": "Fast EMA",
                "type": "number",
                "default": 12,
                "min": 5,
                "max": 50,
            },
            {
                "key": "slow_period",
                "label": "Slow EMA",
                "type": "number",
                "default": 26,
                "min": 10,
                "max": 100,
            },
            {
                "key": "signal_period",
                "label": "Signal",
                "type": "number",
                "default": 9,
                "min": 3,
                "max": 20,
            },
            {
                "key": "risk_per_trade",
                "label": "Risk %",
                "type": "number",
                "default": 0.015,
                "min": 0.005,
                "max": 0.05,
                "step": 0.005,
            },
        ],
    },
    "supertrend": {
        "display_name": "Supertrend ⭐",
        "description": "ATR-based trend flip (~62-68% win rate)",
        "params": [
            {
                "key": "atr_period",
                "label": "ATR Period",
                "type": "number",
                "default": 10,
                "min": 5,
                "max": 30,
            },
            {
                "key": "multiplier",
                "label": "Multiplier",
                "type": "number",
                "default": 3.0,
                "min": 1.0,
                "max": 5.0,
                "step": 0.5,
            },
            {
                "key": "risk_per_trade",
                "label": "Risk %",
                "type": "number",
                "default": 0.015,
                "min": 0.005,
                "max": 0.05,
                "step": 0.005,
            },
        ],
    },
    # ── NEW STRATEGIES ────────────────────────────────────────────
    "vwap_ema": {
        "display_name": "VWAP + EMA 📊",
        "description": "Long above VWAP & EMA, exit below either (institutional + momentum)",
        "params": [
            {
                "key": "ema_period",
                "label": "EMA Period",
                "type": "number",
                "default": 21,
                "min": 5,
                "max": 100,
            },
            {
                "key": "vwap_lookback",
                "label": "VWAP Lookback",
                "type": "number",
                "default": 20,
                "min": 5,
                "max": 50,
            },
            {
                "key": "risk_per_trade",
                "label": "Risk %",
                "type": "number",
                "default": 0.015,
                "min": 0.005,
                "max": 0.05,
                "step": 0.005,
            },
        ],
    },
    "fvg_strategy": {
        "display_name": "Fair Value Gap 🎯",
        "description": "Smart Money / ICT — buy discount FVG zones, sell at premium FVGs",
        "params": [
            {
                "key": "fvg_lookback",
                "label": "FVG Lookback",
                "type": "number",
                "default": 20,
                "min": 5,
                "max": 50,
            },
            {
                "key": "min_gap_pct",
                "label": "Min Gap %",
                "type": "number",
                "default": 0.003,
                "min": 0.001,
                "max": 0.02,
                "step": 0.001,
            },
            {
                "key": "risk_per_trade",
                "label": "Risk %",
                "type": "number",
                "default": 0.015,
                "min": 0.005,
                "max": 0.05,
                "step": 0.005,
            },
        ],
    },
    "swift_algo": {
        "display_name": "Swift Algo X ⚡",
        "description": "7-indicator confluence: Supertrend + VWAP + EMA stack + RSI + Volume + MACD (~65-72% WR)",
        "params": [
            {
                "key": "ema_fast",
                "label": "EMA Fast",
                "type": "number",
                "default": 9,
                "min": 3,
                "max": 20,
            },
            {
                "key": "ema_mid",
                "label": "EMA Mid",
                "type": "number",
                "default": 21,
                "min": 10,
                "max": 50,
            },
            {
                "key": "ema_slow",
                "label": "EMA Slow",
                "type": "number",
                "default": 50,
                "min": 20,
                "max": 100,
            },
            {
                "key": "rsi_min",
                "label": "RSI Min",
                "type": "number",
                "default": 45,
                "min": 30,
                "max": 55,
            },
            {
                "key": "rsi_max",
                "label": "RSI Max",
                "type": "number",
                "default": 75,
                "min": 60,
                "max": 85,
            },
            {
                "key": "vol_mult",
                "label": "Vol Mult",
                "type": "number",
                "default": 1.5,
                "min": 1.0,
                "max": 3.0,
                "step": 0.1,
            },
            {
                "key": "risk_per_trade",
                "label": "Risk %",
                "type": "number",
                "default": 0.015,
                "min": 0.005,
                "max": 0.05,
                "step": 0.005,
            },
        ],
    },
}


def get_strategy_info() -> list:
    """
    Scan strategies/stocks/ directory and return metadata for all found strategies.
    """
    result = []
    strat_dir = "strategies/stocks"

    if not os.path.isdir(strat_dir):
        log.warning(f"Strategy directory not found: {strat_dir}")
        return result

    for fname in sorted(os.listdir(strat_dir)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue

        module_name = fname[:-3]  # strip .py
        try:
            mod = importlib.import_module(f"strategies.stocks.{module_name}")
            # Find the strategy class (inherits BaseStrategy or has generate_signals)
            for cls_name, cls in inspect.getmembers(mod, inspect.isclass):
                if cls.__module__ != mod.__name__:
                    continue
                if not hasattr(cls, "generate_signals"):
                    continue

                meta = STRATEGY_PARAMS.get(module_name, {})
                result.append(
                    {
                        "name": module_name,
                        "display_name": meta.get("display_name", cls_name),
                        "description": meta.get("description", ""),
                        "params": meta.get("params", []),
                        "file": fname,
                        "asset_class": "stocks",
                    }
                )
                break  # one class per file
        except Exception as e:
            log.error(f"Failed to load {module_name}: {e}")

    log.info(f"Loaded {len(result)} strategies: {[s['name'] for s in result]}")
    return result
