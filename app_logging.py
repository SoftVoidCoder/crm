import logging
import os
from logging.handlers import RotatingFileHandler


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "korda.log")
_LOGGING_READY = False


def init_app_logging():
    global _LOGGING_READY
    if _LOGGING_READY:
        return

    os.makedirs(LOG_DIR, exist_ok=True)

    root_logger = logging.getLogger("korda")
    root_logger.setLevel(logging.INFO)
    root_logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_500_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    if not root_logger.handlers:
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

    _LOGGING_READY = True


def get_logger(name: str):
    init_app_logging()
    return logging.getLogger(f"korda.{name}")
