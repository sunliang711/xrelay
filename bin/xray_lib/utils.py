"""Shared utility functions."""

import os
import shlex
import shutil
import subprocess

from .log import get_logger

LOGGER = get_logger(__name__)


def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def get_editor() -> str:
    for env_key in ("EDITOR", "editor"):
        val = os.environ.get(env_key)
        if val:
            return val
    for ed in ("nvim", "vim", "vi"):
        if command_exists(ed):
            return ed
    return "vi"


def build_editor_cmd(*paths: str) -> list[str]:
    return [*shlex.split(get_editor()), *paths]


def run_as_root(*args, check=True):
    """Run a command, prepending sudo when not already root."""
    if os.getuid() == 0:
        cmd = list(args)
    else:
        if not command_exists("sudo"):
            LOGGER.critical("'sudo' is required but not found")
            raise SystemExit(1)
        cmd = ["sudo"] + list(args)
    LOGGER.info("Running command: %s", shlex.join(cmd))
    try:
        result = subprocess.run(cmd, check=check)
    except subprocess.CalledProcessError:
        LOGGER.error("Command failed: %s", shlex.join(cmd))
        raise
    if result.returncode != 0:
        LOGGER.warning("Command exited with code %s: %s", result.returncode, shlex.join(cmd))
    return result


def run(*args, check=True, capture=False):
    """Run a command and optionally capture output."""
    cmd = list(args)
    LOGGER.info("Running command: %s", shlex.join(cmd))
    if capture:
        try:
            result = subprocess.run(cmd, check=check, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            LOGGER.error("Command failed: %s", shlex.join(cmd))
            raise
    else:
        try:
            result = subprocess.run(cmd, check=check)
        except subprocess.CalledProcessError:
            LOGGER.error("Command failed: %s", shlex.join(cmd))
            raise
    if result.returncode != 0:
        LOGGER.warning("Command exited with code %s: %s", result.returncode, shlex.join(cmd))
    return result


def ensure_dir(*dirs):
    for d in dirs:
        os.makedirs(d, exist_ok=True)
