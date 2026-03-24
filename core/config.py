import os
from dotenv import load_dotenv

load_dotenv()
os.makedirs("data", exist_ok=True)
os.makedirs("logs", exist_ok=True)


class Config:
    ALPACA_API_KEY = os.getenv("APCA_API_KEY_ID", os.getenv("ALPACA_API_KEY", ""))
    ALPACA_SECRET_KEY = os.getenv(
        "APCA_API_SECRET_KEY", os.getenv("ALPACA_SECRET_KEY", "")
    )
    ALPACA_MODE = os.getenv("ALPACA_MODE", "paper")

    @property
    def ALPACA_BASE_URL(self):
        if self.ALPACA_MODE == "live":
            return "https://api.alpaca.markets"
        return "https://paper-api.alpaca.markets"

    APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "change-me")
    DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")
    MAX_PORTFOLIO_RISK_PCT = float(os.getenv("MAX_PORTFOLIO_RISK_PCT", 0.02))
    MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", 0.05))
    MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", 5))
    BASE_DIR = os.getcwd()
    DB_PATH = os.path.join(BASE_DIR, "data", "trading.db")

    DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

    LOG_FILE = "logs/trading.log"


config = Config()
