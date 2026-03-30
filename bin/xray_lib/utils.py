"""Shared utility functions."""

import os
import shutil
import subprocess
import sys


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


def run_as_root(*args, check=True):
    """Run a command, prepending sudo when not already root."""
    if os.getuid() == 0:
        cmd = list(args)
    else:
        if not command_exists("sudo"):
            print("Error: 'sudo' is required but not found.", file=sys.stderr)
            sys.exit(1)
        cmd = ["sudo"] + list(args)
    print(f"[Running]: {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def run(*args, check=True, capture=False):
    """Run a command and optionally capture output."""
    cmd = list(args)
    if capture:
        return subprocess.run(cmd, check=check, capture_output=True, text=True)
    return subprocess.run(cmd, check=check)


def ensure_dir(*dirs):
    for d in dirs:
        os.makedirs(d, exist_ok=True)
