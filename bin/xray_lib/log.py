"""Standard-library logging helpers for xrelay."""

import logging
import sys
from typing import Optional

LOGGER_NAME = "xrelay"
SUCCESS = 25
FATAL = logging.CRITICAL
ERROR = logging.ERROR
WARNING = logging.WARNING
INFO = logging.INFO
DEBUG = logging.DEBUG

_ANSI = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "bold": "\033[1m",
    "reset": "\033[0m",
}

_LEVEL_STYLE = {
    FATAL: ("red", "bold"),
    ERROR: ("red", "bold"),
    WARNING: ("yellow", "bold"),
    SUCCESS: ("green", "bold"),
    INFO: ("blue", "bold"),
    DEBUG: ("cyan", "bold"),
}

_LEVELS = {
    "fatal": FATAL,
    "error": ERROR,
    "warning": WARNING,
    "info": INFO,
    "success": SUCCESS,
    "debug": DEBUG,
}


logging.addLevelName(SUCCESS, "SUCCESS")


def _logger_success(self: logging.Logger, message, *args, **kwargs):
    if self.isEnabledFor(SUCCESS):
        self._log(SUCCESS, message, args, **kwargs)


if not hasattr(logging.Logger, "success"):
    logging.Logger.success = _logger_success


class ColorFormatter(logging.Formatter):
    """Render colored, timestamped log lines."""

    def __init__(self):
        super().__init__(datefmt="%Y-%m-%d %H:%M:%S")
        self._use_color = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, self.datefmt)
        level = f"[{record.levelname}]".ljust(11)

        if self._use_color:
            codes = "".join(_ANSI.get(name, "") for name in _LEVEL_STYLE.get(record.levelno, ()))
            level = f"{codes}{level}{_ANSI['reset']}"

        message = record.getMessage()
        output = f"[{timestamp}] {level} {message}"
        if record.exc_info:
            output = f"{output}\n{self.formatException(record.exc_info)}"
        return output


def configure_logging(level_name: str = "info") -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(ColorFormatter())
        logger.addHandler(handler)
        logger.propagate = False

    logger.setLevel(_LEVELS.get(level_name.lower(), INFO))
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    configure_logging()
    if not name:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def set_log_level(level_name: str):
    configure_logging(level_name)


def log(level: int, message: str):
    logger = get_logger()
    logger.log(level, message)
    if level == FATAL:
        raise SystemExit(1)
