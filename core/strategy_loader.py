import os
import importlib
import inspect
from core.strategy_base import BaseStrategy
from core.logger import get_logger

log = get_logger("strategy_loader")

STRATEGY_DIRS = ["strategies/stocks", "strategies/options", "strategies/crypto"]

# Strategy metadata — parameters shown in the dashboard
STRATEGY_PARAMS = {
    "ma_crossover": {
        "display_name": "MA Crossover",
        "description": "Golden/death cross using two moving averages",
        "params": [
            {
                "key": "fast_ma",
                "label": "Fast MA period",
                "type": "number",
                "default": 50,
                "min": 5,
                "max": 199,
            },
            {
                "key": "slow_ma",
                "label": "Slow MA period",
                "type": "number",
                "default": 200,
                "min": 10,
                "max": 500,
            },
        ],
    },
    "rsi_strategy": {
        "display_name": "RSI Mean Reversion",
        "description": "Buy oversold, sell overbought using RSI",
        "params": [
            {
                "key": "rsi_period",
                "label": "RSI period",
                "type": "number",
                "default": 14,
                "min": 5,
                "max": 30,
            },
            {
                "key": "oversold",
                "label": "Oversold level",
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
        ],
    },
    "institutional_ema": {
        "display_name": "Institutional EMA",
        "description": "EMA 9/21/50/200 with ATR-based position sizing",
        "params": [
            {
                "key": "ema_fast",
                "label": "Fast EMA",
                "type": "number",
                "default": 9,
                "min": 3,
                "max": 50,
            },
            {
                "key": "ema_mid",
                "label": "Mid EMA",
                "type": "number",
                "default": 21,
                "min": 10,
                "max": 100,
            },
            {
                "key": "ema_slow",
                "label": "Slow EMA",
                "type": "number",
                "default": 50,
                "min": 20,
                "max": 200,
            },
            {
                "key": "risk_per_trade",
                "label": "Risk % / trade",
                "type": "number",
                "default": 0.01,
                "min": 0.005,
                "max": 0.05,
                "step": 0.005,
            },
        ],
    },
}


def discover_strategies():
    found = {}
    for folder in STRATEGY_DIRS:
        if not os.path.exists(folder):
            continue
        asset_class = folder.split("/")[-1]
        for fname in sorted(os.listdir(folder)):
            if (
                not fname.endswith(".py")
                or fname.startswith("_")
                or fname.startswith("README")
            ):
                continue
            module_path = folder.replace("/", ".") + "." + fname[:-3]
            try:
                mod = importlib.import_module(module_path)
                for name, obj in inspect.getmembers(mod, inspect.isclass):
                    if (
                        issubclass(obj, BaseStrategy)
                        and obj is not BaseStrategy
                        and obj.__module__ == module_path
                        and not obj.__name__.startswith("Base")
                    ):
                        key = fname[:-3]
                        meta = STRATEGY_PARAMS.get(key, {})
                        found[key] = {
                            "class": obj,
                            "module": module_path,
                            "file": fname,
                            "asset_class": asset_class,
                            "display_name": meta.get("display_name", name),
                            "description": meta.get("description", ""),
                            "params": meta.get("params", []),
                        }
                        log.info(f"Discovered: {key} ({asset_class})")
            except Exception as e:
                log.error(f"Could not load {module_path}: {e}")
    return found


def load_all_strategies(broker):
    strategies = []
    for name, info in discover_strategies().items():
        try:
            instance = info["class"](broker)
            strategies.append(instance)
        except Exception as e:
            log.error(f"Could not instantiate {name}: {e}")
    return strategies


def load_strategy_by_name(name, broker):
    discovered = discover_strategies()
    if name not in discovered:
        raise ValueError(f"Strategy '{name}' not found")
    return discovered[name]["class"](broker)


def get_strategy_info():
    return [
        {
            "name": k,
            "display_name": v["display_name"],
            "description": v["description"],
            "asset_class": v["asset_class"],
            "file": v["file"],
            "params": v["params"],
        }
        for k, v in discover_strategies().items()
    ]
