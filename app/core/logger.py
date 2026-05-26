import logging
import sys
import uuid
from logging.handlers import RotatingFileHandler
from contextvars import ContextVar

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_FILE = "logs/app.log"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(LOG_FORMAT)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3)
    file_handler.setFormatter(formatter)

    logger.addHandler(stdout_handler)
    logger.addHandler(file_handler)

    return logger


request_id_var: ContextVar[str] = ContextVar("request_id", default="no-request-id")


def get_request_id() -> str:
    return request_id_var.get()


def set_request_id(request_id: str = None) -> str:
    rid = request_id or str(uuid.uuid4())
    request_id_var.set(rid)
    return rid