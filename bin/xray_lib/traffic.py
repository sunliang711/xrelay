"""Traffic monitoring via xray stats API (gRPC)."""

import json
import os
import subprocess
import sys
import time
from datetime import datetime

from .config import ETC_DIR, TRAFFIC_DIR, XRAY_BIN
from .utils import build_editor_cmd


class TrafficError(RuntimeError):
    """Raised when traffic data cannot be collected safely."""


def _load_runtime_config(config_name: str) -> dict:
    json_file = os.path.join(ETC_DIR, f"{config_name}.json")
    if not os.path.exists(json_file):
        raise TrafficError(f"config not found: {json_file}")

    try:
        with open(json_file) as file_obj:
            return json.load(file_obj)
    except json.JSONDecodeError as exc:
        raise TrafficError(f"invalid JSON config: {json_file}") from exc


def _extract_api_port(config: dict, config_name: str) -> int:
    try:
        listen = config["api"]["listen"]
        _, port_str = str(listen).rsplit(":", 1)
        return int(port_str)
    except (KeyError, TypeError, ValueError) as exc:
        raise TrafficError(f"cannot determine api_port for {config_name}") from exc


def _extract_tags(config: dict) -> list[str]:
    tags = []
    for inbound in config.get("inbounds", []):
        if isinstance(inbound, dict):
            tag = inbound.get("tag")
            if isinstance(tag, str):
                tags.append(tag)
    return tags


def _extract_emails(config: dict) -> list[str]:
    emails = []
    for inbound in config.get("inbounds", []):
        if not isinstance(inbound, dict):
            continue
        settings = inbound.get("settings", {})
        if not isinstance(settings, dict):
            continue
        for client in settings.get("clients", []):
            if isinstance(client, dict):
                email = client.get("email")
                if isinstance(email, str):
                    emails.append(email)
    return emails


def _parse_tag(tag: str):
    parts = tag.split(":", 2)
    typ = parts[0] if len(parts) > 0 else ""
    port = parts[1] if len(parts) > 1 else ""
    remark = parts[2] if len(parts) > 2 else ""
    return typ, port, remark


def _query_stats(api_port: int, pattern: str = "", reset: bool = False) -> dict[str, int]:
    if api_port <= 0:
        raise TrafficError("api_port must be greater than 0")

    server = f"127.0.0.1:{api_port}"
    cmd = [XRAY_BIN, "api", "statsquery", "-s", server]
    if pattern:
        cmd.extend(["-pattern", pattern])
    if reset:
        cmd.append("-reset")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except FileNotFoundError as exc:
        raise TrafficError(f"xray binary not found at {XRAY_BIN}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TrafficError("xray api query timed out") from exc

    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise TrafficError(f"xray api error: {err}")

    stdout = result.stdout.strip()
    if not stdout:
        return {}

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise TrafficError("failed to parse xray api output") from exc

    stats = {}
    for item in data.get("stat", []):
        name = item.get("name", "")
        value = int(item.get("value", 0))
        stats[name] = value

    return stats


def _format_bytes(n: int) -> str:
    return f"{n:,}"


def _snapshot(config_name: str, require_stats: bool = False, reset: bool = False) -> str:
    config = _load_runtime_config(config_name)
    api_port = _extract_api_port(config, config_name)
    tags = _extract_tags(config)
    emails = _extract_emails(config)
    stats = _query_stats(api_port, reset=reset)

    if not stats:
        if require_stats:
            raise TrafficError(
                f"no stats data for xray@{config_name} (api address: 127.0.0.1:{api_port})"
            )
        return (
            f"(no stats data — is xray@{config_name} running?)\n"
            f"(api address: 127.0.0.1:{api_port})"
        )

    lines: list[str] = []
    lines.append("=== Inbound Traffic ===")
    lines.append(
        f"{'type':<10}{'port':<10}{'remark':<20}{'uplink':<20}{'downlink':<20}{'total':<20}"
    )
    lines.append("-" * 100)

    for tag in tags:
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

    outbound_stats = {k: v for k, v in stats.items() if k.startswith("outbound>>>")}
    if outbound_stats:
        lines.append("")
        lines.append("=== Outbound Traffic ===")
        lines.append(f"{'name':<30}{'uplink':<20}{'downlink':<20}{'total':<20}")
        lines.append("-" * 90)

        outbound_tags: dict[str, dict[str, int]] = {}
        for key, value in outbound_stats.items():
            parts = key.split(">>>")
            if len(parts) >= 4:
                outbound_tag = parts[1]
                direction = parts[3]
                outbound_tags.setdefault(outbound_tag, {"uplink": 0, "downlink": 0})
                outbound_tags[outbound_tag][direction] = value

        for outbound_tag, directions in sorted(outbound_tags.items()):
            up = directions.get("uplink", 0)
            down = directions.get("downlink", 0)
            total = up + down
            lines.append(
                f"{outbound_tag:<30}"
                f"{_format_bytes(up):<20}{_format_bytes(down):<20}{_format_bytes(total):<20}"
            )

        lines.append("-" * 90)

    return "\n".join(lines)


def _require_config_name(args, usage):
    if not args:
        print(f"Usage: traffic {usage}", file=sys.stderr)
        return None
    return args[0]


def cmd_traffic(action: str, *args) -> int:
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
    return handler(list(args))


def _do_show(args):
    name = _require_config_name(args, "show <config_name>")
    if not name:
        return 1
    try:
        snapshot = _snapshot(name)
    except TrafficError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    print()
    print(snapshot)
    return 0


def _do_monitor(args):
    name = _require_config_name(args, "monitor <config_name>")
    if not name:
        return 1

    sys.stdout.write("\033[?25l")
    sys.stdout.write("\033[2J")
    sys.stdout.flush()
    try:
        while True:
            try:
                snapshot = _snapshot(name)
            except TrafficError as exc:
                snapshot = f"Error: {exc}"

            sys.stdout.write("\033[H")
            output = (
                datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                + "\n\n"
                + snapshot
                + "\n\nPress <C-c> to quit."
            )
            sys.stdout.write(output)
            sys.stdout.write("\033[J")
            sys.stdout.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def _append_snapshot(filepath: str, snapshot: str):
    with open(filepath, "a") as file_obj:
        file_obj.write(f"{datetime.now():%Y-%m-%dT%H:%M:%S}\n")
        file_obj.write(snapshot + "\n\n")


def _do_save_day(args):
    name = _require_config_name(args, "saveDay <config_name>")
    if not name:
        return 1
    os.makedirs(TRAFFIC_DIR, exist_ok=True)
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-year-{datetime.now():%Y}")
    try:
        snapshot = _snapshot(name, require_stats=True, reset=True)
    except TrafficError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _append_snapshot(filepath, snapshot)
    print(f"saved daily snapshot to {filepath}")
    return 0


def _do_save_hour(args):
    name = _require_config_name(args, "saveHour <config_name>")
    if not name:
        return 1
    os.makedirs(TRAFFIC_DIR, exist_ok=True)
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-month-{datetime.now():%Y%m}")
    try:
        snapshot = _snapshot(name, require_stats=True)
    except TrafficError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _append_snapshot(filepath, snapshot)
    print(f"saved hourly snapshot to {filepath}")
    return 0


def _do_view_day(args):
    name = _require_config_name(args, "day <config_name>")
    if not name:
        return 1
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-year-{datetime.now():%Y}")
    if not os.path.exists(filepath):
        print(f"No data file: {filepath}")
        return 1
    return subprocess.run(build_editor_cmd(filepath)).returncode


def _do_view_hour(args):
    name = _require_config_name(args, "hour <config_name>")
    if not name:
        return 1
    filepath = os.path.join(TRAFFIC_DIR, f"{name}-month-{datetime.now():%Y%m}")
    if not os.path.exists(filepath):
        print(f"No data file: {filepath}")
        return 1
    return subprocess.run(build_editor_cmd(filepath)).returncode
