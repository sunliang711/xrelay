"""Service management operations (add / start / stop / restart / remove …)."""

import os
import shutil
import subprocess
import sys

from .config import (
    ETC_DIR,
    TEMPLATE_DIR,
    XRAY_BIN,
    YAML2JSON_PYTHON,
    YAML2JSON_SCRIPT,
    YAML2JSON_TEMPLATE,
    SERVICE_NAME_TPL,
)
from .log import log, ERROR, INFO, SUCCESS
from .utils import run_as_root, ensure_dir, get_editor
from .traffic import add_watch_ports, del_watch_ports
from .cron import add_cron, del_cron


def _svc(name: str) -> str:
    return SERVICE_NAME_TPL.format(name)


# ── Config generation ────────────────────────────────────────────────────


def gen_config(name: str) -> bool:
    """Run yaml2json to produce <name>.json from <name>.yaml."""
    yaml_file = os.path.join(ETC_DIR, f"{name}.yaml")
    json_file = os.path.join(ETC_DIR, f"{name}.json")
    template_dir = os.path.dirname(YAML2JSON_TEMPLATE)
    template_name = os.path.basename(YAML2JSON_TEMPLATE)

    if not os.path.exists(yaml_file):
        log(ERROR, f"Config not found: {yaml_file}")
        return False
    if not os.path.exists(YAML2JSON_SCRIPT):
        log(ERROR, f"yaml2json not found: {YAML2JSON_SCRIPT}")
        return False
    if not os.path.exists(YAML2JSON_PYTHON):
        log(ERROR, f"yaml2json venv not found: {YAML2JSON_PYTHON}")
        return False
    if not os.path.exists(YAML2JSON_TEMPLATE):
        log(ERROR, f"Template not found: {YAML2JSON_TEMPLATE}")
        return False

    log(INFO, f"Generate {name}.json from {name}.yaml")
    result = subprocess.run(
        [
            YAML2JSON_PYTHON,
            YAML2JSON_SCRIPT,
            "--template",
            template_name,
            "--config",
            yaml_file,
            "--output",
            json_file,
        ],
        capture_output=True, text=True,
        cwd=template_dir,
    )
    if result.returncode != 0:
        log(ERROR, f"yaml2json failed: {result.stderr}")
        return False

    log(SUCCESS, f"Generated {json_file}")
    return True


# ── Public sub-commands ──────────────────────────────────────────────────


def cmd_add(name: str) -> int:
    ensure_dir(ETC_DIR)
    yaml_file = os.path.join(ETC_DIR, f"{name}.yaml")

    if os.path.exists(yaml_file):
        log(ERROR, f"{name} already exists")
        return 1

    template_yaml = os.path.join(TEMPLATE_DIR, "config.yaml")
    if os.path.exists(template_yaml):
        shutil.copy2(template_yaml, yaml_file)
    else:
        with open(yaml_file, "w") as f:
            f.write("# xray config\n")

    subprocess.run([get_editor(), yaml_file])

    if not gen_config(name):
        return 1

    run_as_root("systemctl", "daemon-reload")
    run_as_root("systemctl", "enable", _svc(name))
    log(SUCCESS, f"Service {_svc(name)} enabled")
    return 0


def cmd_list() -> int:
    if not os.path.isdir(ETC_DIR):
        print("No configs found.")
        return 0

    configs = sorted(f for f in os.listdir(ETC_DIR) if f.endswith(".yaml"))
    for c in configs:
        print(c)
    return 0


def cmd_config(name: str) -> int:
    yaml_file = os.path.join(ETC_DIR, f"{name}.yaml")
    if not os.path.exists(yaml_file):
        log(ERROR, f"No such config: {name}")
        return 1

    mtime_before = os.path.getmtime(yaml_file)
    subprocess.run([get_editor(), yaml_file])
    mtime_after = os.path.getmtime(yaml_file)

    if mtime_before != mtime_after:
        print("Config changed, regenerating and restarting...")
        return cmd_restart(name)
    return 0


def cmd_start(name: str) -> int:
    if not gen_config(name):
        return 1
    run_as_root("systemctl", "start", _svc(name))
    return 0


def cmd_stop(name: str) -> int:
    run_as_root("systemctl", "stop", _svc(name))
    return 0


def cmd_restart(name: str) -> int:
    cmd_stop(name)
    return cmd_start(name)


def cmd_log(name: str) -> int:
    run_as_root("journalctl", "-u", f"xray@{name}", "-f")
    return 0


def cmd_remove(name: str) -> int:
    json_file = os.path.join(ETC_DIR, f"{name}.json")
    yaml_file = os.path.join(ETC_DIR, f"{name}.yaml")

    if not os.path.exists(json_file) and not os.path.exists(yaml_file):
        log(ERROR, f"No {name} service found")
        return 1

    log(INFO, f"Removing {name}...")
    run_as_root("systemctl", "stop", _svc(name), check=False)
    run_as_root("systemctl", "disable", _svc(name), check=False)

    for path in (yaml_file, json_file):
        if os.path.exists(path):
            os.remove(path)
            print(f"  Removed {path}")

    log(SUCCESS, f"Removed {name}")
    return 0


def cmd_remove_all() -> int:
    if not os.path.isdir(ETC_DIR):
        return 0
    names = sorted(f[:-5] for f in os.listdir(ETC_DIR) if f.endswith(".yaml"))
    for name in names:
        cmd_remove(name)
    return 0


# ── Systemd hook commands ────────────────────────────────────────────────


def cmd_start_pre(name: str) -> int:
    """Called by ExecStartPre — verify everything is in place."""
    print("Enter _start_pre()...")

    if not os.path.exists(XRAY_BIN):
        print(f"Error: xray not found at {XRAY_BIN}", file=sys.stderr)
        return 1

    json_file = os.path.join(ETC_DIR, f"{name}.json")
    if not os.path.exists(json_file):
        print(f"Error: config not found: {json_file}", file=sys.stderr)
        return 1

    return 0


def cmd_start_post(name: str) -> int:
    """Called by ExecStartPost — add iptables rules and cron jobs."""
    print("Enter _start_post()...")
    add_watch_ports(name)
    add_cron(name)
    return 0


def cmd_stop_post(name: str) -> int:
    """Called by ExecStopPost — clean up iptables rules and cron jobs."""
    print("Enter _stop_post()...")
    del_watch_ports(name)
    del_cron(name)
    return 0
