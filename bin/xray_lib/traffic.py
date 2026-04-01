"""Traffic monitoring via xray stats API (gRPC)."""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional

from .config import ETC_DIR, TRAFFIC_DIR, XRAY_BIN
from .log import get_logger
from .utils import build_editor_cmd

LOGGER = get_logger(__name__)


class TrafficError(RuntimeError):
    """Raised when traffic data cannot be collected safely."""


STATE_DIR = os.path.join(TRAFFIC_DIR, ".state")
GB = 1024 ** 3
MB = 1024 ** 2


def _ensure_traffic_dirs():
    os.makedirs(TRAFFIC_DIR, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)


def _state_file(name: str) -> str:
    return os.path.join(STATE_DIR, f"{name}-latest.json")


def _day_state_file(name: str, now: datetime) -> str:
    return os.path.join(STATE_DIR, f"{name}-day-{now:%Y%m%d}.json")


def _month_state_file(name: str, now: datetime) -> str:
    return os.path.join(STATE_DIR, f"{name}-month-{now:%Y%m}.json")


def _hour_report_file(name: str, now: datetime) -> str:
    return os.path.join(TRAFFIC_DIR, f"{name}-hour-{now:%Y%m}.log")


def _day_report_file(name: str, now: datetime) -> str:
    return os.path.join(TRAFFIC_DIR, f"{name}-day-{now:%Y%m%d}.log")


def _month_report_file(name: str, now: datetime) -> str:
    return os.path.join(TRAFFIC_DIR, f"{name}-month-{now:%Y%m}.log")


def _load_json_file(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as file_obj:
            return json.load(file_obj)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json_file(path: str, data):
    with open(path, "w") as file_obj:
        json.dump(data, file_obj, indent=2, sort_keys=True)
        file_obj.write("\n")


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


def _query_stats(api_port: int) -> dict[str, int]:
    if api_port <= 0:
        raise TrafficError("api_port must be greater than 0")

    server = f"127.0.0.1:{api_port}"
    cmd = [XRAY_BIN, "api", "statsquery", "-s", server]

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


def _format_usage(size_bytes: int) -> str:
    if size_bytes < GB:
        return f"{size_bytes / MB:.2f} MB"
    gb_part = size_bytes // GB
    mb_part = (size_bytes % GB) / MB
    return f"{gb_part} GB + {mb_part:.2f} MB"


def _collect_snapshot(config_name: str) -> dict:
    config = _load_runtime_config(config_name)
    api_port = _extract_api_port(config, config_name)
    tags = _extract_tags(config)
    emails = _extract_emails(config)
    stats = _query_stats(api_port)

    if not stats:
        raise TrafficError(
            f"no stats data for xray@{config_name} (api address: 127.0.0.1:{api_port})"
        )

    inbound = {}
    for tag in tags:
        typ, port, remark = _parse_tag(tag)
        if not port:
            continue
        up_key = f"inbound>>>{tag}>>>traffic>>>uplink"
        down_key = f"inbound>>>{tag}>>>traffic>>>downlink"
        inbound[tag] = {
            "type": typ,
            "port": port,
            "remark": remark,
            "uplink": stats.get(up_key, 0),
            "downlink": stats.get(down_key, 0),
        }

    user = {}
    for email in emails:
        up_key = f"user>>>{email}>>>traffic>>>uplink"
        down_key = f"user>>>{email}>>>traffic>>>downlink"
        user[email] = {
            "email": email,
            "uplink": stats.get(up_key, 0),
            "downlink": stats.get(down_key, 0),
        }

    outbound = {}
    for key, value in stats.items():
        if not key.startswith("outbound>>>"):
            continue
        parts = key.split(">>>")
        if len(parts) < 4:
            continue
        outbound_tag = parts[1]
        direction = parts[3]
        outbound.setdefault(
            outbound_tag,
            {"name": outbound_tag, "uplink": 0, "downlink": 0},
        )
        outbound[outbound_tag][direction] = value

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "inbound": inbound,
        "user": user,
        "outbound": outbound,
    }


def _delta_section(current_section: dict, previous_section: dict, label_fields: list[str]) -> dict:
    delta = {}
    for key, current in current_section.items():
        previous = previous_section.get(key, {})
        up = current.get("uplink", 0)
        down = current.get("downlink", 0)
        prev_up = previous.get("uplink", 0)
        prev_down = previous.get("downlink", 0)

        if up < prev_up or down < prev_down:
            delta_up = up
            delta_down = down
        else:
            delta_up = up - prev_up
            delta_down = down - prev_down

        item = {
            "uplink": delta_up,
            "downlink": delta_down,
        }
        for field in label_fields:
            if field in current:
                item[field] = current[field]
        delta[key] = item
    return delta


def _compute_delta(current_snapshot: dict, previous_snapshot: Optional[dict]) -> dict:
    previous_snapshot = previous_snapshot or {}
    return {
        "timestamp": current_snapshot["timestamp"],
        "inbound": _delta_section(
            current_snapshot.get("inbound", {}),
            previous_snapshot.get("inbound", {}),
            ["type", "port", "remark"],
        ),
        "user": _delta_section(
            current_snapshot.get("user", {}),
            previous_snapshot.get("user", {}),
            ["email"],
        ),
        "outbound": _delta_section(
            current_snapshot.get("outbound", {}),
            previous_snapshot.get("outbound", {}),
            ["name"],
        ),
    }


def _merge_sections(base: dict, delta: dict, label_fields: list[str]) -> dict:
    merged = dict(base)
    for key, item in delta.items():
        target = dict(merged.get(key, {}))
        for field in label_fields:
            if field in item:
                target[field] = item[field]
        target["uplink"] = int(target.get("uplink", 0)) + int(item.get("uplink", 0))
        target["downlink"] = int(target.get("downlink", 0)) + int(item.get("downlink", 0))
        merged[key] = target
    return merged


def _merge_snapshot(base: dict, delta: dict, timestamp: str) -> dict:
    return {
        "timestamp": timestamp,
        "inbound": _merge_sections(
            base.get("inbound", {}),
            delta.get("inbound", {}),
            ["type", "port", "remark"],
        ),
        "user": _merge_sections(
            base.get("user", {}),
            delta.get("user", {}),
            ["email"],
        ),
        "outbound": _merge_sections(
            base.get("outbound", {}),
            delta.get("outbound", {}),
            ["name"],
        ),
    }


def _snapshot_to_text(snapshot: dict, title: str) -> str:
    lines = [snapshot["timestamp"], "", title, "", "=== Inbound Traffic ==="]
    lines.append(
        f"{'type':<10}{'port':<10}{'remark':<20}{'uplink':<22}{'downlink':<22}{'total':<22}"
    )
    lines.append("-" * 106)

    inbound_items = sorted(
        snapshot.get("inbound", {}).values(),
        key=lambda item: (str(item.get("port", "")), str(item.get("remark", ""))),
    )
    for item in inbound_items:
        uplink = int(item.get("uplink", 0))
        downlink = int(item.get("downlink", 0))
        total = uplink + downlink
        lines.append(
            f"{str(item.get('type', '')):<10}{str(item.get('port', '')):<10}{str(item.get('remark', '')):<20}"
            f"{_format_usage(uplink):<22}{_format_usage(downlink):<22}{_format_usage(total):<22}"
        )

    lines.append("-" * 106)

    user_items = sorted(snapshot.get("user", {}).values(), key=lambda item: item.get("email", ""))
    if user_items:
        lines.append("")
        lines.append("=== User (vmess) Traffic ===")
        lines.append(f"{'email':<30}{'uplink':<22}{'downlink':<22}{'total':<22}")
        lines.append("-" * 96)
        for item in user_items:
            uplink = int(item.get("uplink", 0))
            downlink = int(item.get("downlink", 0))
            total = uplink + downlink
            lines.append(
                f"{str(item.get('email', '')):<30}"
                f"{_format_usage(uplink):<22}{_format_usage(downlink):<22}{_format_usage(total):<22}"
            )
        lines.append("-" * 96)

    outbound_items = sorted(snapshot.get("outbound", {}).values(), key=lambda item: item.get("name", ""))
    if outbound_items:
        lines.append("")
        lines.append("=== Outbound Traffic ===")
        lines.append(f"{'name':<30}{'uplink':<22}{'downlink':<22}{'total':<22}")
        lines.append("-" * 96)
        for item in outbound_items:
            uplink = int(item.get("uplink", 0))
            downlink = int(item.get("downlink", 0))
            total = uplink + downlink
            lines.append(
                f"{str(item.get('name', '')):<30}"
                f"{_format_usage(uplink):<22}{_format_usage(downlink):<22}{_format_usage(total):<22}"
            )
        lines.append("-" * 96)

    return "\n".join(lines)


def _write_text_report(path: str, content: str):
    with open(path, "w") as file_obj:
        file_obj.write(content)
        file_obj.write("\n")


def _append_text_report(path: str, content: str):
    with open(path, "a") as file_obj:
        file_obj.write(content)
        file_obj.write("\n\n")


def _store_snapshot(name: str, now: datetime, current: dict, delta: dict):
    _ensure_traffic_dirs()

    previous_day = _load_json_file(_day_state_file(name, now), {"timestamp": delta["timestamp"], "inbound": {}, "user": {}, "outbound": {}})
    previous_month = _load_json_file(_month_state_file(name, now), {"timestamp": delta["timestamp"], "inbound": {}, "user": {}, "outbound": {}})

    day_summary = _merge_snapshot(previous_day, delta, delta["timestamp"])
    month_summary = _merge_snapshot(previous_month, delta, delta["timestamp"])

    _write_json_file(_state_file(name), current)
    _write_json_file(_day_state_file(name, now), day_summary)
    _write_json_file(_month_state_file(name, now), month_summary)

    _append_text_report(
        _hour_report_file(name, now),
        _snapshot_to_text(delta, "Hourly Usage"),
    )
    _write_text_report(
        _day_report_file(name, now),
        _snapshot_to_text(day_summary, "Daily Usage"),
    )
    _write_text_report(
        _month_report_file(name, now),
        _snapshot_to_text(month_summary, "Monthly Usage"),
    )

    return {
        "hour": _hour_report_file(name, now),
        "day": _day_report_file(name, now),
        "month": _month_report_file(name, now),
    }


def _save_usage(name: str):
    now = datetime.now()
    _ensure_traffic_dirs()
    current_snapshot = _collect_snapshot(name)
    previous_snapshot = _load_json_file(_state_file(name), None)
    delta_snapshot = _compute_delta(current_snapshot, previous_snapshot)
    paths = _store_snapshot(name, now, current_snapshot, delta_snapshot)
    return delta_snapshot, paths


def _show_live_snapshot(name: str) -> str:
    snapshot = _collect_snapshot(name)
    return _snapshot_to_text(snapshot, "Live Usage")


def _require_config_name(args, usage):
    if not args:
        LOGGER.error("Usage: traffic %s", usage)
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
        "month": _do_view_month,
    }
    handler = dispatch.get(action)
    if handler is None:
        LOGGER.error("Unknown traffic action: %s", action)
        LOGGER.info("Available actions: %s", ", ".join(dispatch.keys()))
        return 1
    return handler(list(args))


def _do_show(args):
    name = _require_config_name(args, "show <config_name>")
    if not name:
        return 1
    try:
        print(_show_live_snapshot(name))
    except TrafficError as exc:
        LOGGER.error("%s", exc)
        return 1
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
                output = _show_live_snapshot(name)
            except TrafficError as exc:
                output = f"Error: {exc}"
            sys.stdout.write("\033[H")
            sys.stdout.write(output)
            sys.stdout.write("\n\nPress <C-c> to quit.")
            sys.stdout.write("\033[J")
            sys.stdout.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def _do_save_hour(args):
    name = _require_config_name(args, "saveHour <config_name>")
    if not name:
        return 1

    try:
        delta_snapshot, paths = _save_usage(name)
    except TrafficError as exc:
        LOGGER.error("%s", exc)
        return 1

    print(_snapshot_to_text(delta_snapshot, "Hourly Usage"))
    print()
    print(f"hourly log   : {paths['hour']}")
    print(f"daily usage  : {paths['day']}")
    print(f"monthly usage: {paths['month']}")
    return 0


def _do_save_day(args):
    name = _require_config_name(args, "saveDay <config_name>")
    if not name:
        return 1

    try:
        delta_snapshot, paths = _save_usage(name)
    except TrafficError as exc:
        LOGGER.error("%s", exc)
        return 1

    print(_snapshot_to_text(delta_snapshot, "Usage Since Last Save"))
    print()
    print(f"daily usage  : {paths['day']}")
    print(f"monthly usage: {paths['month']}")
    return 0


def _open_report(path: str) -> int:
    if not os.path.exists(path):
        LOGGER.error("No data file: %s", path)
        return 1
    return subprocess.run(build_editor_cmd(path)).returncode


def _do_view_day(args):
    name = _require_config_name(args, "day <config_name>")
    if not name:
        return 1
    return _open_report(_day_report_file(name, datetime.now()))


def _do_view_hour(args):
    name = _require_config_name(args, "hour <config_name>")
    if not name:
        return 1
    return _open_report(_hour_report_file(name, datetime.now()))


def _do_view_month(args):
    name = _require_config_name(args, "month <config_name>")
    if not name:
        return 1
    return _open_report(_month_report_file(name, datetime.now()))
