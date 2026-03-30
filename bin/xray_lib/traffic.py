"""Traffic monitoring via iptables."""

import os
import re
import subprocess
import sys
import time
from datetime import datetime

from .config import ETC_DIR, TRAFFIC_DIR
from .utils import get_editor


# ── Tag parsing ──────────────────────────────────────────────────────────


def _get_tags(config_name: str) -> list:
    """Extract "tag" values from the JSON config file."""
    json_file = os.path.join(ETC_DIR, f"{config_name}.json")
    if not os.path.exists(json_file):
        return []
    with open(json_file) as f:
        content = f.read()
    return [m.group(1) for m in re.finditer(r'"tag"\s*:\s*"([^"]+)"', content)]


def _parse_tag(tag: str):
    parts = tag.split(":")
    typ = parts[0] if len(parts) > 0 else ""
    port = parts[1] if len(parts) > 1 else ""
    remark = parts[2] if len(parts) > 2 else ""
    return typ, port, remark


# ── iptables watch ports ─────────────────────────────────────────────────


def add_watch_ports(config_name: str):
    print("_addWatchPorts...")
    for tag in _get_tags(config_name):
        _typ, port, _remark = _parse_tag(tag)
        if not port:
            continue

        out = subprocess.run(
            ["sudo", "iptables", "-L", "OUTPUT", "-n", "--line-numbers"],
            capture_output=True, text=True,
        )
        if f"spt:{port}" not in out.stdout:
            print(f"Add port: {port} to OUTPUT")
            subprocess.run(
                ["sudo", "iptables", "-A", "OUTPUT", "-p", "tcp", "--sport", port],
                check=False,
            )

        inp = subprocess.run(
            ["sudo", "iptables", "-L", "INPUT", "-n", "--line-numbers"],
            capture_output=True, text=True,
        )
        if f"dpt:{port}" not in inp.stdout:
            print(f"Add port: {port} to INPUT")
            subprocess.run(
                ["sudo", "iptables", "-A", "INPUT", "-p", "tcp", "--dport", port],
                check=False,
            )


def del_watch_ports(config_name: str):
    print("_delWatchPorts...")
    for tag in _get_tags(config_name):
        _typ, port, _remark = _parse_tag(tag)
        if not port:
            continue
        print(f"Clear port: {port}")
        subprocess.run(
            ["sudo", "iptables", "-D", "OUTPUT", "-p", "tcp", "--sport", port],
            check=False,
        )
        subprocess.run(
            ["sudo", "iptables", "-D", "INPUT", "-p", "tcp", "--dport", port],
            check=False,
        )


# ── Snapshot & zero ──────────────────────────────────────────────────────


def _snapshot(config_name: str, in_byte: str = "") -> str:
    """Capture traffic statistics from iptables for all tagged ports."""
    chains = ["OUTPUT", "INPUT"]
    tags = _get_tags(config_name)
    lines: list[str] = []

    for chain in chains:
        cmd = ["sudo", "iptables", "-L", chain, "-nv"]
        if in_byte:
            cmd.append(in_byte)
        result = subprocess.run(cmd, capture_output=True, text=True)
        output_lines = result.stdout.strip().split("\n")

        if output_lines:
            lines.append(output_lines[0])
        lines.append(
            f"{'protocol':<10}{'port':<10}{'remark':<22}{'bytes':<18}{'packets':<18}"
        )

        for tag in tags:
            typ, port, remark = _parse_tag(tag)
            if not port:
                continue

            pattern = re.compile(rf"(dpt|spt):{port}\b")
            found = False
            for line in output_lines:
                if pattern.search(line):
                    fields = line.split()
                    if len(fields) >= 10:
                        pks, bs, pro = fields[0], fields[1], fields[2]
                        pt = fields[9]
                        try:
                            bs = f"{int(bs):,}"
                        except ValueError:
                            pass
                        try:
                            pks = f"{int(pks):,}"
                        except ValueError:
                            pass
                        lines.append(
                            f"{pro:<10}{pt:<10}{typ}->{remark:<22}{bs:<18}{pks:<18}"
                        )
                        found = True
                    break
            if not found:
                lines.append(f"no such port data: {port}")

        lines.append("-" * 69)

    return "\n".join(lines)


def _zero(config_name: str):
    """Zero iptables counters for monitored ports."""
    for tag in _get_tags(config_name):
        _typ, port, _remark = _parse_tag(tag)
        if not port:
            continue
        print(f"zero port: {port}...")
        for chain, direction in [("INPUT", "dpt"), ("OUTPUT", "spt")]:
            result = subprocess.run(
                ["sudo", "iptables", "-L", chain, "-n", "--line-numbers"],
                capture_output=True, text=True,
            )
            for line in result.stdout.split("\n"):
                if re.search(rf"{direction}:{port}\b", line):
                    line_num = line.split()[0]
                    subprocess.run(
                        ["sudo", "iptables", "-L", "-Z", chain, line_num],
                        check=False,
                    )
                    break


# ── High-level traffic commands ──────────────────────────────────────────


def _require_config_name(args, usage):
    if not args:
        print(f"Usage: traffic {usage}", file=sys.stderr)
        return None
    return args[0]


def cmd_traffic(action: str, *args) -> int:
    """Dispatch traffic sub-commands."""
    dispatch = {
        "monitor": _do_monitor,
        "saveDay": _do_save_day,
        "saveHour": _do_save_hour,
        "day": _do_view_day,
        "hour": _do_view_hour,
        "_addWatchPorts": lambda a: add_watch_ports(a[0]) if a else None,
        "_delWatchPorts": lambda a: del_watch_ports(a[0]) if a else None,
    }
    handler = dispatch.get(action)
    if handler is None:
        print(f"Unknown traffic action: {action}", file=sys.stderr)
        return 1
    handler(list(args))
    return 0


def _do_monitor(args):
    name = _require_config_name(args, "monitor <config_name> [-x]")
    if not name:
        return
    in_byte = args[1] if len(args) > 1 else ""
    print("Press <C-c> to quit.")
    try:
        while True:
            os.system("clear")
            print(datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
            print()
            print(_snapshot(name, in_byte))
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def _do_save_day(args):
    name = _require_config_name(args, "saveDay <config_name>")
    if not name:
        return
    os.makedirs(TRAFFIC_DIR, exist_ok=True)
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-year-{datetime.now():%Y}")
    print("saveDay...")
    with open(filepath, "a") as f:
        f.write(f"{datetime.now():%Y-%m-%dT%H:%M:%S}\n")
        f.write(_snapshot(name) + "\n")
    _zero(name)


def _do_save_hour(args):
    name = _require_config_name(args, "saveHour <config_name>")
    if not name:
        return
    os.makedirs(TRAFFIC_DIR, exist_ok=True)
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-month-{datetime.now():%Y%m}")
    print(f"saveHour to {filepath}")
    with open(filepath, "a") as f:
        f.write(f"{datetime.now():%Y-%m-%dT%H:%M:%S}\n")
        f.write(_snapshot(name) + "\n")


def _do_view_day(args):
    name = _require_config_name(args, "day <config_name>")
    if not name:
        return
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-year-{datetime.now():%Y}")
    subprocess.run([get_editor(), filepath])


def _do_view_hour(args):
    name = _require_config_name(args, "hour <config_name>")
    if not name:
        return
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-month-{datetime.now():%Y%m}")
    subprocess.run([get_editor(), filepath])
