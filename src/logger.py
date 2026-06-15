import logging
import sys
import os
from datetime import datetime


def setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"

    os.makedirs("logs", exist_ok=True)
    log_file = os.path.join("logs", f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.stream.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%H:%M:%S",
        handlers=[
            stream_handler,
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("github").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(f"logging to {log_file}")
