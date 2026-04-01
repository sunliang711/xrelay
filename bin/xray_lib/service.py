"""Service management operations (add / start / stop / restart / remove …)."""

import os
import re
import shutil
import subprocess

from .config import (
    ETC_DIR,
    SERVICE_NAME_TPL,
    TEMPLATE_DIR,
    XRAY_BIN,
    YAML2JSON_PYTHON,
    YAML2JSON_SCRIPT,
)
from .cron import add_cron, del_cron
from .log import get_logger
from .utils import build_editor_cmd, ensure_dir, run_as_root

LOGGER = get_logger(__name__)


def _svc(name: str) -> str:
    return SERVICE_NAME_TPL.format(name)


def _validate_name(name: str) -> bool:
    if not name:
        LOGGER.error("Instance name is required")
        return False
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", name):
        LOGGER.error(
            "Instance name may only contain letters, numbers, dot, underscore, dash, and @",
        )
        return False
    return True


def _config_paths(name: str) -> tuple[str, str]:
    return (
        os.path.join(ETC_DIR, f"{name}.yaml"),
        os.path.join(ETC_DIR, f"{name}.json"),
    )


# ── Config generation ────────────────────────────────────────────────────


def gen_config(name: str) -> bool:
    """Run yaml2json to produce <name>.json from <name>.yaml."""
    yaml_file, json_file = _config_paths(name)

    if not os.path.exists(yaml_file):
        LOGGER.error("Config not found: %s", yaml_file)
        return False
    if not os.path.exists(YAML2JSON_SCRIPT):
        LOGGER.error("yaml2json not found: %s", YAML2JSON_SCRIPT)
        return False
    if not os.path.exists(YAML2JSON_PYTHON):
        LOGGER.error("yaml2json venv not found: %s", YAML2JSON_PYTHON)
        return False

    LOGGER.info("Generating %s.json from %s.yaml", name, name)
    result = subprocess.run(
        [
            YAML2JSON_PYTHON,
            YAML2JSON_SCRIPT,
            "--config",
            yaml_file,
            "--output",
            json_file,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or "unknown error"
        LOGGER.error("yaml2json failed: %s", error)
        return False

    LOGGER.success("Generated %s", json_file)
    return True


# ── Public sub-commands ──────────────────────────────────────────────────


def cmd_add(name: str) -> int:
    if not _validate_name(name):
        return 1

    ensure_dir(ETC_DIR)
    yaml_file, _ = _config_paths(name)

    if os.path.exists(yaml_file):
        LOGGER.error("%s already exists", name)
        return 1

    template_yaml = os.path.join(TEMPLATE_DIR, "config.yaml")
    LOGGER.info("Creating config for instance %s", name)
    if os.path.exists(template_yaml):
        shutil.copy2(template_yaml, yaml_file)
        LOGGER.info("Copied template config to %s", yaml_file)
    else:
        with open(yaml_file, "w") as f:
            f.write("# xray config\n")
        LOGGER.info("Created blank config at %s", yaml_file)

    LOGGER.info("Opening config editor for %s", yaml_file)
    edit_result = subprocess.run(build_editor_cmd(yaml_file))
    if edit_result.returncode != 0:
        LOGGER.error("Editor exited with code %s", edit_result.returncode)
        return 1

    if not gen_config(name):
        return 1

    LOGGER.info("Reloading systemd units before enabling %s", _svc(name))
    run_as_root("systemctl", "daemon-reload")
    return cmd_enable(name)


def cmd_list() -> int:
    if not os.path.isdir(ETC_DIR):
        LOGGER.info("No configs found in %s", ETC_DIR)
        return 0

    LOGGER.info("Listing configs in %s", ETC_DIR)
    configs = sorted(f for f in os.listdir(ETC_DIR) if f.endswith(".yaml"))
    if not configs:
        LOGGER.info("No configs found in %s", ETC_DIR)
        return 0
    for c in configs:
        print(c)
    return 0


def cmd_config(name: str) -> int:
    if not _validate_name(name):
        return 1

    yaml_file, _ = _config_paths(name)
    if not os.path.exists(yaml_file):
        LOGGER.error("No such config: %s", name)
        return 1

    LOGGER.info("Opening config editor for %s", yaml_file)
    mtime_before = os.path.getmtime(yaml_file)
    edit_result = subprocess.run(build_editor_cmd(yaml_file))
    if edit_result.returncode != 0:
        LOGGER.error("Editor exited with code %s", edit_result.returncode)
        return 1
    mtime_after = os.path.getmtime(yaml_file)

    if mtime_before != mtime_after:
        LOGGER.info("Config changed for %s; regenerating JSON and restarting service", name)
        return cmd_restart(name)
    LOGGER.info("Config unchanged for %s; skipping restart", name)
    return 0


def cmd_start(name: str) -> int:
    if not _validate_name(name):
        return 1
    LOGGER.info("Starting service %s", _svc(name))
    if not gen_config(name):
        return 1
    run_as_root("systemctl", "start", _svc(name))
    LOGGER.success("Started service %s", _svc(name))
    return 0


def cmd_stop(name: str) -> int:
    if not _validate_name(name):
        return 1
    LOGGER.info("Stopping service %s", _svc(name))
    run_as_root("systemctl", "stop", _svc(name))
    LOGGER.success("Stopped service %s", _svc(name))
    return 0


def cmd_restart(name: str) -> int:
    if not _validate_name(name):
        return 1
    LOGGER.info("Restarting service %s", _svc(name))
    cmd_stop(name)
    return cmd_start(name)


def cmd_enable(name: str) -> int:
    if not _validate_name(name):
        return 1
    LOGGER.info("Enabling service %s", _svc(name))
    run_as_root("systemctl", "enable", _svc(name))
    LOGGER.success("Enabled service %s", _svc(name))
    return 0


def cmd_disable(name: str) -> int:
    if not _validate_name(name):
        return 1
    LOGGER.info("Disabling service %s", _svc(name))
    run_as_root("systemctl", "disable", _svc(name))
    LOGGER.success("Disabled service %s", _svc(name))
    return 0


def cmd_log(name: str) -> int:
    if not _validate_name(name):
        return 1
    LOGGER.info("Following journal logs for service %s", _svc(name))
    try:
        run_as_root("journalctl", "-u", f"xray@{name}", "-f")
    except (KeyboardInterrupt, subprocess.CalledProcessError):
        pass
    return 0


def cmd_remove(name: str) -> int:
    if not _validate_name(name):
        return 1

    yaml_file, json_file = _config_paths(name)

    if not os.path.exists(json_file) and not os.path.exists(yaml_file):
        LOGGER.error("No %s service found", name)
        return 1

    LOGGER.info("Removing instance %s", name)
    run_as_root("systemctl", "stop", _svc(name), check=False)
    LOGGER.info("Disabling service %s before deleting files", _svc(name))
    run_as_root("systemctl", "disable", _svc(name), check=False)

    for path in (yaml_file, json_file):
        if os.path.exists(path):
            os.remove(path)
            LOGGER.info("Removed %s", path)

    LOGGER.success("Removed instance %s", name)
    return 0


def cmd_remove_all() -> int:
    if not os.path.isdir(ETC_DIR):
        LOGGER.info("No configs found in %s", ETC_DIR)
        return 0
    names = sorted(f[:-5] for f in os.listdir(ETC_DIR) if f.endswith(".yaml"))
    if not names:
        LOGGER.info("No configs found in %s", ETC_DIR)
        return 0
    LOGGER.info("Removing all instances: %s", ", ".join(names))
    for name in names:
        cmd_remove(name)
    return 0


# ── Systemd hook commands ────────────────────────────────────────────────


def cmd_start_pre(name: str) -> int:
    """Called by ExecStartPre — verify everything is in place."""
    LOGGER.info("Running start pre-check for %s", name)

    if not os.path.exists(XRAY_BIN):
        LOGGER.error("xray not found at %s", XRAY_BIN)
        return 1

    _, json_file = _config_paths(name)
    if not os.path.exists(json_file):
        LOGGER.error("Config not found: %s", json_file)
        return 1

    LOGGER.success("Start pre-check passed for %s", name)
    return 0


def cmd_start_post(name: str) -> int:
    """Called by ExecStartPost — add iptables rules and cron jobs."""
    LOGGER.info("Running start post-hook for %s", name)
    # add_watch_ports(name)
    # add_cron(name)
    return 0


def cmd_stop_post(name: str) -> int:
    """Called by ExecStopPost — clean up iptables rules and cron jobs."""
    LOGGER.info("Running stop post-hook for %s", name)
    # del_watch_ports(name)
    # del_cron(name)
    return 0
