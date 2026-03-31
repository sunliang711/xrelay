"""Traffic monitoring via xray stats API (gRPC).

Replaces the old iptables-based approach.  Now every query goes through
    xray api statsquery -s 127.0.0.1:<api_port>
which talks to the StatsService that is already configured in the
generated JSON config.
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

from .config import ETC_DIR, TRAFFIC_DIR, XRAY_BIN
from .utils import get_editor

# ── Config helpers ───────────────────────────────────────────────────────


def _get_api_port(config_name: str) -> int:
    """Read api_port from the generated JSON config (api.listen field).

    The JSON contains:  "api": {"listen": "127.0.0.1:<port>", ...}
    """
    json_file = os.path.join(ETC_DIR, f"{config_name}.json")
    if not os.path.exists(json_file):
        return 0
    try:
        with open(json_file) as f:
            data = json.load(f)
        listen = data["api"]["listen"]  # e.g. "127.0.0.1:18080"
        _, port_str = listen.rsplit(":", 1)
        return int(port_str)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 0


def _get_tags(config_name: str) -> list:
    """Extract "tag" values from the JSON config file."""
    json_file = os.path.join(ETC_DIR, f"{config_name}.json")
    if not os.path.exists(json_file):
        return []
    with open(json_file) as f:
        content = f.read()
    return [m.group(1) for m in re.finditer(r'"tag"\s*:\s*"([^"]+)"', content)]


def _get_emails(config_name: str) -> list:
    """Extract "email" values from the JSON config file (vmess per-user)."""
    json_file = os.path.join(ETC_DIR, f"{config_name}.json")
    if not os.path.exists(json_file):
        return []
    with open(json_file) as f:
        content = f.read()
    return [m.group(1) for m in re.finditer(r'"email"\s*:\s*"([^"]+)"', content)]


def _parse_tag(tag: str):
    """Parse  type:port:remark  from a tag string."""
    parts = tag.split(":")
    typ = parts[0] if len(parts) > 0 else ""
    port = parts[1] if len(parts) > 1 else ""
    remark = parts[2] if len(parts) > 2 else ""
    return typ, port, remark


# ── xray stats API ──────────────────────────────────────────────────────


def _query_stats(api_port: int, pattern: str = "", reset: bool = False) -> dict:
    """Call `xray api statsquery` and return {stat_name: value} dict.

    The xray CLI outputs JSON like:
        {"stat":[{"name":"inbound>>>tag>>>traffic>>>uplink","value":"12345"}, ...]}
    """
    if api_port <= 0:
        return {}

    server = f"127.0.0.1:{api_port}"
    cmd = [XRAY_BIN, "api", "statsquery", "-s", server]
    if pattern:
        cmd.extend(["-pattern", pattern])
    if reset:
        cmd.append("-reset")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        print(f"Error: xray binary not found at {XRAY_BIN}", file=sys.stderr)
        return {}
    except subprocess.TimeoutExpired:
        print("Error: xray api query timed out", file=sys.stderr)
        return {}

    if result.returncode != 0:
        # stderr may contain connection errors when xray is not running
        err = result.stderr.strip()
        if err:
            print(f"xray api error: {err}", file=sys.stderr)
        return {}

    stdout = result.stdout.strip()
    if not stdout:
        return {}

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        print("Error: failed to parse xray api output", file=sys.stderr)
        return {}

    stats = {}
    for item in data.get("stat", []):
        name = item.get("name", "")
        value = int(item.get("value", 0))
        stats[name] = value

    return stats


def _format_bytes(n: int) -> str:
    """Human-friendly byte count with comma separators."""
    return f"{n:,}"


# ── Snapshot ─────────────────────────────────────────────────────────────


def _snapshot(config_name: str, reset: bool = False) -> str:
    """Capture traffic statistics from xray stats API for all tagged
    inbounds and per-user (email) entries.

    Returns a formatted multi-line string.
    """
    api_port = _get_api_port(config_name)
    if api_port <= 0:
        return f"Error: cannot determine api_port for {config_name}"

    tags = _get_tags(config_name)
    emails = _get_emails(config_name)
    stats = _query_stats(api_port, reset=reset)

    if not stats and not reset:
        return (
            f"(no stats data — is xray@{config_name} running?)\n"
            f"(api address: 127.0.0.1:{api_port})"
        )

    lines: list[str] = []

    # ── Inbound stats ────────────────────────────────────────────
    lines.append("=== Inbound Traffic ===")
    lines.append(
        f"{'type':<10}{'port':<10}{'remark':<20}{'uplink':<20}{'downlink':<20}{'total':<20}"
    )
    lines.append("-" * 100)

    for tag in tags:
        # skip internal tags (e.g. "api", "vmess" without colon)
        typ, port, remark = _parse_tag(tag)
        if not port:
            continue

        up_key = f"inbound>>>{tag}>>>traffic>>>uplink"
        down_key = f"inbound>>>{tag}>>>traffic>>>downlink"
        up = stats.get(up_key, 0)
        down = stats.get(down_key, 0)
        total = up + down

        lines.append(
            f"{typ:<10}{port:<10}{remark:<20}"
            f"{_format_bytes(up):<20}{_format_bytes(down):<20}{_format_bytes(total):<20}"
        )

    lines.append("-" * 100)

    # ── Per-user (email) stats — vmess clients ───────────────────
    if emails:
        lines.append("")
        lines.append("=== User (vmess) Traffic ===")
        lines.append(f"{'email':<30}{'uplink':<20}{'downlink':<20}{'total':<20}")
        lines.append("-" * 90)

        for email in emails:
            up_key = f"user>>>{email}>>>traffic>>>uplink"
            down_key = f"user>>>{email}>>>traffic>>>downlink"
            up = stats.get(up_key, 0)
            down = stats.get(down_key, 0)
            total = up + down

            lines.append(
                f"{email:<30}"
                f"{_format_bytes(up):<20}{_format_bytes(down):<20}{_format_bytes(total):<20}"
            )

        lines.append("-" * 90)

    # ── Outbound stats (if any) ──────────────────────────────────
    outbound_stats = {k: v for k, v in stats.items() if k.startswith("outbound>>>")}
    if outbound_stats:
        lines.append("")
        lines.append("=== Outbound Traffic ===")
        lines.append(f"{'name':<30}{'uplink':<20}{'downlink':<20}{'total':<20}")
        lines.append("-" * 90)

        # group by outbound tag
        outbound_tags: dict[str, dict[str, int]] = {}
        for k, v in outbound_stats.items():
            # outbound>>>tag>>>traffic>>>uplink
            parts = k.split(">>>")
            if len(parts) >= 4:
                ob_tag = parts[1]
                direction = parts[3]  # uplink / downlink
                outbound_tags.setdefault(ob_tag, {"uplink": 0, "downlink": 0})
                outbound_tags[ob_tag][direction] = v

        for ob_tag, dirs in sorted(outbound_tags.items()):
            up = dirs.get("uplink", 0)
            down = dirs.get("downlink", 0)
            total = up + down
            lines.append(
                f"{ob_tag:<30}"
                f"{_format_bytes(up):<20}{_format_bytes(down):<20}{_format_bytes(total):<20}"
            )

        lines.append("-" * 90)

    return "\n".join(lines)


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
        "show": _do_show,
        "saveDay": _do_save_day,
        "saveHour": _do_save_hour,
        "day": _do_view_day,
        "hour": _do_view_hour,
    }
    handler = dispatch.get(action)
    if handler is None:
        print(f"Unknown traffic action: {action}", file=sys.stderr)
        print(f"Available actions: {', '.join(dispatch.keys())}", file=sys.stderr)
        return 1
    handler(list(args))
    return 0


def _do_show(args):
    """Print a single snapshot and exit."""
    name = _require_config_name(args, "show <config_name>")
    if not name:
        return
    print(datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    print()
    print(_snapshot(name))


def _do_monitor(args):
    """Continuously refresh traffic stats (like `watch`)."""
    name = _require_config_name(args, "monitor <config_name>")
    if not name:
        return
    print("Press <C-c> to quit.")
    try:
        while True:
            os.system("clear")
            print(datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
            print()
            print(_snapshot(name))
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def _do_save_day(args):
    """Append current stats to the yearly log file and reset counters."""
    name = _require_config_name(args, "saveDay <config_name>")
    if not name:
        return
    os.makedirs(TRAFFIC_DIR, exist_ok=True)
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-year-{datetime.now():%Y}")
    print("saveDay...")
    snapshot = _snapshot(name, reset=True)
    with open(filepath, "a") as f:
        f.write(f"{datetime.now():%Y-%m-%dT%H:%M:%S}\n")
        f.write(snapshot + "\n\n")


def _do_save_hour(args):
    """Append current stats to the monthly log file (no counter reset)."""
    name = _require_config_name(args, "saveHour <config_name>")
    if not name:
        return
    os.makedirs(TRAFFIC_DIR, exist_ok=True)
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-month-{datetime.now():%Y%m}")
    print(f"saveHour to {filepath}")
    snapshot = _snapshot(name)
    with open(filepath, "a") as f:
        f.write(f"{datetime.now():%Y-%m-%dT%H:%M:%S}\n")
        f.write(snapshot + "\n\n")


def _do_view_day(args):
    name = _require_config_name(args, "day <config_name>")
    if not name:
        return
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-year-{datetime.now():%Y}")
    if not os.path.exists(filepath):
        print(f"No data file: {filepath}")
        return
    subprocess.run([get_editor(), filepath])


def _do_view_hour(args):
    name = _require_config_name(args, "hour <config_name>")
    if not name:
        return
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-month-{datetime.now():%Y%m}")
    if not os.path.exists(filepath):
        print(f"No data file: {filepath}")
        return
    subprocess.run([get_editor(), filepath])
