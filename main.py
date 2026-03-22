import asyncio
import uvicorn
from dashboard.server import app
from core.logger import get_logger

log = get_logger("main")


if __name__ == "__main__":
    log.info("Starting trading system...")
    uvicorn.run(
        "dashboard.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
