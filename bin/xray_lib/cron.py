"""Cron job management for traffic statistics."""

import os
import subprocess
import tempfile

from .config import CRON_BEGIN, CRON_END, XRAY_PY
from .log import get_logger

LOGGER = get_logger(__name__)


def _get_crontab() -> str:
    result = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    )
    return result.stdout if result.returncode == 0 else ""


def _set_crontab(content: str):
    fd, path = tempfile.mkstemp(suffix=".cron")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        subprocess.run(["crontab", path], check=True)
    finally:
        os.unlink(path)


def add_cron(config_name: str):
    LOGGER.info("Adding traffic cron jobs for %s", config_name)
    begin_marker = f"{CRON_BEGIN}-{config_name}"
    end_marker = f"{CRON_END}-{config_name}"

    current = _get_crontab()
    if begin_marker in current:
        LOGGER.info("Traffic cron jobs already exist for %s", config_name)
        return

    block = (
        f"{begin_marker}\n"
        f"0 * * * * {XRAY_PY} traffic saveHour {config_name}\n"
        f"59 23 * * * {XRAY_PY} traffic saveDay {config_name}\n"
        f"{end_marker}\n"
    )
    new = current.rstrip("\n") + "\n" + block if current.strip() else block
    _set_crontab(new)
    LOGGER.success("Added traffic cron jobs for %s", config_name)


def del_cron(config_name: str):
    LOGGER.info("Removing traffic cron jobs for %s", config_name)
    begin_marker = f"{CRON_BEGIN}-{config_name}"
    end_marker = f"{CRON_END}-{config_name}"

    current = _get_crontab()
    if begin_marker not in current:
        LOGGER.info("No traffic cron jobs found for %s", config_name)
        return

    lines = current.split("\n")
    filtered, inside = [], False
    for line in lines:
        if begin_marker in line:
            inside = True
            continue
        if end_marker in line:
            inside = False
            continue
        if not inside:
            filtered.append(line)

    _set_crontab("\n".join(filtered))
    LOGGER.success("Removed traffic cron jobs for %s", config_name)
