import os
import uvicorn
from core.logger import get_logger

log = get_logger("main")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    log.info(f"Starting on port {port}...")
    uvicorn.run(
        "dashboard.server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
import os

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))  # Railway provides PORT
    uvicorn.run("main:app", host="0.0.0.0", port=port)