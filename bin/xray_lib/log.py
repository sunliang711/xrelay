"""Colored logging with level support."""

import sys
from datetime import datetime

FATAL = 1
ERROR = 2
WARNING = 3
SUCCESS = 4
INFO = 5
DEBUG = 6

_current_level = INFO

_LEVEL_NAMES = {
    FATAL: "FATAL",
    ERROR: "ERROR",
    WARNING: "WARNING",
    SUCCESS: "SUCCESS",
    INFO: "INFO",
    DEBUG: "DEBUG",
}

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

_use_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def set_log_level(level_name: str):
    global _current_level
    mapping = {
        "fatal": FATAL,
        "error": ERROR,
        "warning": WARNING,
        "success": SUCCESS,
        "info": INFO,
        "debug": DEBUG,
    }
    _current_level = mapping.get(level_name.lower(), INFO)


def log(level: int, message: str):
    if level > _current_level:
        return

    name = _LEVEL_NAMES.get(level, "?")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    padded = f"[{name}]".ljust(10)

    if _use_color:
        codes = "".join(_ANSI.get(c, "") for c in _LEVEL_STYLE.get(level, ()))
        reset = _ANSI["reset"]
        print(f"{codes}[{ts}] {padded}{reset} {message}")
    else:
        print(f"[{ts}] {padded} {message}")

    if level == FATAL:
        sys.exit(1)
