#!/usr/bin/env python3
"""xray service management CLI.

Manages xray instances via systemd template units (xray@<name>.service).
Supports adding, starting, stopping, restarting, viewing logs,
traffic monitoring, and removing service instances.
"""

import argparse
import os
import subprocess
import sys
from typing import Optional

# Resolve symlinks so imports work when invoked via /usr/local/bin/xray.py
_real_dir = os.path.dirname(os.path.realpath(__file__))
if _real_dir not in sys.path:
    sys.path.insert(0, _real_dir)

from xray_lib.log import get_logger, set_log_level  # noqa: E402
from xray_lib.service import (  # noqa: E402
    cmd_add,
    cmd_config,
    cmd_disable,
    cmd_list,
    cmd_log,
    cmd_remove,
    cmd_remove_all,
    cmd_enable,
    cmd_restart,
    cmd_start,
    cmd_start_post,
    cmd_start_pre,
    cmd_stop,
    cmd_stop_post,
)
from xray_lib.import_export import cmd_export, cmd_import  # noqa: E402
from xray_lib.traffic import cmd_traffic  # noqa: E402

LOGGER = get_logger(__name__)


def _strip_yaml(name: str) -> str:
    return name.removesuffix(".yaml")


def _command_summary(args) -> Optional[str]:
    name = getattr(args, "name", None)
    svc = f"xray@{name}.service" if name else None
    summaries = {
        "add": f"Create a new config, generate JSON, and enable {svc}",
        "list": "List all configured xray instances",
        "config": f"Edit {name}.yaml and restart the service if the config changes",
        "start": f"Generate JSON and start {svc}",
        "stop": f"Stop {svc}",
        "restart": f"Regenerate JSON and restart {svc}",
        "enable": f"Enable {svc} to start automatically",
        "disable": f"Disable {svc} from starting automatically",
        "log": f"Follow journalctl logs for {svc}",
        "remove": f"Stop {svc}, disable it, and delete its config files",
        "removeAll": "Stop, disable, and delete every configured instance",
        "export": "Export selected or all xray instance configs",
        "import": f"Import xray instance configs from {getattr(args, 'path', '')}; existing configs are skipped",
        "traffic": f"Run traffic action '{getattr(args, 'action', '')}'".strip(),
        "_start_pre": f"Run the systemd start pre-check for {name}",
        "_start_post": f"Run the systemd start post-hook for {name}",
        "_stop_post": f"Run the systemd stop post-hook for {name}",
    }
    return summaries.get(args.command)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="xray.py",
        description="xray service management (systemd template units)",
    )
    parser.add_argument(
        "-l",
        "--log-level",
        choices=["fatal", "error", "warning", "info", "success", "debug"],
        default="info",
        help="Set log level",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ── public commands ─────────────────────────────────────────────
    p = sub.add_parser("add", help="Create a new xray config and enable the service")
    p.add_argument("name", help="Instance name")

    sub.add_parser("list", help="List all config files")

    p = sub.add_parser("config", help="Edit a config; auto-restart on change")
    p.add_argument("name", help="Instance name")

    p = sub.add_parser("start", help="Generate config JSON and start the service")
    p.add_argument("name", help="Instance name")

    p = sub.add_parser("stop", help="Stop the service")
    p.add_argument("name", help="Instance name")

    p = sub.add_parser("restart", help="Restart the service")
    p.add_argument("name", help="Instance name")

    p = sub.add_parser("enable", help="Enable the service to start automatically")
    p.add_argument("name", help="Instance name")

    p = sub.add_parser("disable", help="Disable the service from starting automatically")
    p.add_argument("name", help="Instance name")

    p = sub.add_parser("log", help="Follow service journal logs")
    p.add_argument("name", help="Instance name")

    p = sub.add_parser("traffic", help="Traffic monitoring (xray stats API)")
    p.add_argument(
        "action", help="Sub-action: monitor / show / saveDay / saveHour / day / hour / month"
    )
    p.add_argument("extra", nargs="*", help="Arguments for the traffic action")

    p = sub.add_parser("remove", help="Stop, disable and delete a service config")
    p.add_argument("name", help="Instance name")

    sub.add_parser("removeAll", help="Remove every service instance")

    p = sub.add_parser("export", help="Export selected or all config files")
    p.add_argument("names", nargs="*", help="Instance names to export")
    p.add_argument("-a", "--all", action="store_true", help="Export all instances")
    p.add_argument("-o", "--output", help="Output zip file")
    p.add_argument("-f", "--force", action="store_true", help="Overwrite output file")

    p = sub.add_parser("import", help="Import config files; existing instances are skipped")
    p.add_argument("path", help="Export zip file or a single YAML config")

    # ── internal hooks (called by systemd ExecStart{Pre,Post} / ExecStopPost)
    for hook in ("_start_pre", "_start_post", "_stop_post"):
        p = sub.add_parser(hook)
        p.add_argument("name")

    args = parser.parse_args()
    set_log_level(args.log_level)

    if not args.command:
        parser.print_help()
        return 0

    name = getattr(args, "name", None)
    if name:
        name = _strip_yaml(name)
        args.name = name

    summary = _command_summary(args)
    if summary:
        LOGGER.info("%s", summary)

    dispatch = {
        "add": lambda: cmd_add(name),
        "list": lambda: cmd_list(),
        "config": lambda: cmd_config(name),
        "start": lambda: cmd_start(name),
        "stop": lambda: cmd_stop(name),
        "restart": lambda: cmd_restart(name),
        "enable": lambda: cmd_enable(name),
        "disable": lambda: cmd_disable(name),
        "log": lambda: cmd_log(name),
        "traffic": lambda: cmd_traffic(args.action, *args.extra),
        "remove": lambda: cmd_remove(name),
        "removeAll": lambda: cmd_remove_all(),
        "export": lambda: cmd_export(args.names, args.output, args.all, args.force),
        "import": lambda: cmd_import(args.path),
        "_start_pre": lambda: cmd_start_pre(name),
        "_start_post": lambda: cmd_start_post(name),
        "_stop_post": lambda: cmd_stop_post(name),
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    try:
        return handler() or 0
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1


if __name__ == "__main__":
    sys.exit(main())
