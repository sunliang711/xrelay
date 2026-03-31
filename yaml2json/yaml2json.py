#!/usr/bin/env python3

import argparse
import json
import logging
from pathlib import Path

import yaml


def setup_log(logfile, log_level):
    log_level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARN,
        "error": logging.ERROR,
        "fatal": logging.FATAL,
    }
    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    date_format = "%Y/%m/%d %H:%M:%S"

    logging.basicConfig(
        filename=logfile,
        level=log_level_map.get(log_level, logging.ERROR),
        format=log_format,
        datefmt=date_format,
    )


class ConfigError(Exception):
    """Raised when the YAML config is invalid."""


def _require_mapping(value, field_name):
    if not isinstance(value, dict):
        raise ConfigError(f"{field_name} must be a mapping")
    return value


def _require_list(value, field_name):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{field_name} must be a list")
    return value


def _require_string(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field_name} must be a non-empty string")
    return value


def _require_int(value, field_name, default=None):
    if value is None and default is not None:
        value = default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field_name} must be an integer") from exc


def _parse_tag(config_name, item):
    tag = _require_string(item.get("tag"), f"{config_name}.tag")
    parts = tag.split(":", 2)
    if len(parts) < 3:
        raise ConfigError(
            f"{config_name}.tag must be in the format type:port:remark, got: {tag}"
        )
    port = _require_int(parts[1], f"{config_name}.tag port")
    item["tag"] = tag
    item["port"] = port
    return item


def _normalize_inbound_list(inbounds, protocol_name):
    items = _require_list(inbounds.get(protocol_name, []), f"inbounds.{protocol_name}")
    normalized = []
    for index, item in enumerate(items, start=1):
        field_name = f"inbounds.{protocol_name}[{index}]"
        normalized.append(_parse_tag(field_name, _require_mapping(item, field_name)))
    return normalized


def _build_shadowsocks_inbound(item):
    return {
        "tag": item["tag"],
        "protocol": "shadowsocks",
        "port": item["port"],
        "settings": {
            "method": _require_string(item.get("cipher"), f"{item['tag']}.cipher"),
            "password": _require_string(
                item.get("password"), f"{item['tag']}.password"
            ),
            "udp": bool(item.get("udp", False)),
            "network": "tcp,udp",
            "level": 0,
            "ota": False,
        },
    }


def _build_vmess_inbound(config, items):
    for item in items:
        _require_string(item.get("uuid"), f"{item['tag']}.uuid")

    return {
        "tag": "vmess",
        "port": _require_int(config.get("vmess_port"), "inbounds.config.vmess_port", 0),
        "protocol": "vmess",
        "settings": {
            "clients": [
                {
                    "email": item["tag"],
                    "id": item["uuid"],
                    "alterId": _require_int(item.get("alterId"), f"{item['tag']}.alterId", 0),
                }
                for item in items
            ]
        },
        "streamSettings": {
            "network": str(config.get("vmess_network", "raw")),
        },
    }


def _build_http_inbound(item):
    settings = {
        "timeout": 0,
        "userLevel": 0,
        "allowTransparent": False,
    }
    username = item.get("username")
    if username:
        settings["accounts"] = [
            {
                "user": _require_string(username, f"{item['tag']}.username"),
                "pass": _require_string(
                    item.get("password"), f"{item['tag']}.password"
                ),
            }
        ]

    return {
        "tag": item["tag"],
        "protocol": "http",
        "port": item["port"],
        "settings": settings,
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls"],
        },
    }


def _build_socks5_inbound(item):
    settings = {
        "udp": bool(item.get("udp", False)),
        "auth": str(item.get("auth", "noauth")),
        "userLevel": 0,
        "ip": "0.0.0.0",
    }
    username = item.get("username")
    if username:
        settings["accounts"] = [
            {
                "user": _require_string(username, f"{item['tag']}.username"),
                "pass": _require_string(
                    item.get("password"), f"{item['tag']}.password"
                ),
            }
        ]

    return {
        "tag": item["tag"],
        "protocol": "socks",
        "port": item["port"],
        "settings": settings,
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls"],
        },
    }


def _load_file_outbound(config_path, outbound):
    file_value = _require_string(outbound.get("file"), "inbounds.outbound.file")
    file_path = Path(file_value)
    if not file_path.is_absolute():
        file_path = Path(config_path).resolve().parent / file_path

    try:
        with open(file_path) as file_obj:
            loaded = json.load(file_obj)
    except FileNotFoundError as exc:
        raise ConfigError(f"outbound file not found: {file_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"outbound file is not valid JSON: {file_path}") from exc

    if isinstance(loaded, list):
        return loaded
    if isinstance(loaded, dict):
        return [loaded]
    raise ConfigError("outbound file must contain a JSON object or array")


def _build_outbounds(config_path, outbound):
    protocol = _require_string(outbound.get("protocol"), "inbounds.outbound.protocol")

    if protocol in {"socks", "http"}:
        server = {
            "address": _require_string(
                outbound.get("server"), "inbounds.outbound.server"
            ),
            "port": _require_int(outbound.get("port"), "inbounds.outbound.port"),
        }
        if outbound.get("auth") == "password":
            server["users"] = [
                {
                    "user": _require_string(
                        outbound.get("username"), "inbounds.outbound.username"
                    ),
                    "pass": _require_string(
                        outbound.get("password"), "inbounds.outbound.password"
                    ),
                }
            ]

        return [
            {
                "protocol": protocol,
                "settings": {"servers": [server]},
                "streamSettings": {
                    "sockopt": {
                        "note": "for transparent proxy",
                        "mark": 255,
                    }
                },
            }
        ]

    if protocol == "vless":
        return [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": _require_string(
                                outbound.get("server"), "inbounds.outbound.server"
                            ),
                            "port": _require_int(
                                outbound.get("port"), "inbounds.outbound.port"
                            ),
                            "users": [
                                {
                                    "id": _require_string(
                                        outbound.get("uuid"),
                                        "inbounds.outbound.uuid",
                                    ),
                                    "flow": str(outbound.get("flow", "")),
                                    "encryption": str(
                                        outbound.get("encryption", "none")
                                    ),
                                    "level": _require_int(
                                        outbound.get("level"),
                                        "inbounds.outbound.level",
                                        0,
                                    ),
                                }
                            ],
                        }
                    ]
                },
                "streamSettings": {
                    "network": str(outbound.get("network", "tcp")),
                    "security": str(outbound.get("security", "none")),
                    "xtlsSettings": {
                        "serverName": _require_string(
                            outbound.get("server"), "inbounds.outbound.server"
                        )
                    },
                },
            }
        ]

    if protocol == "file":
        return _load_file_outbound(config_path, outbound)

    raise ConfigError(f"unsupported outbound protocol: {protocol}")


def build_config(config_path):
    with open(config_path) as config_file:
        data = yaml.safe_load(config_file) or {}

    if not isinstance(data, dict):
        raise ConfigError("root config must be a mapping")

    inbounds = _require_mapping(data.get("inbounds"), "inbounds")
    runtime_config = _require_mapping(inbounds.get("config"), "inbounds.config")
    outbound = _require_mapping(inbounds.get("outbound"), "inbounds.outbound")

    shadowsocks_items = _normalize_inbound_list(inbounds, "shadowsocks")
    vmess_items = _normalize_inbound_list(inbounds, "vmess")
    http_items = _normalize_inbound_list(inbounds, "http")
    socks5_items = _normalize_inbound_list(inbounds, "socks5")

    log_access = runtime_config.get("log_access")
    log_error = runtime_config.get("log_error")
    legacy_logfile = runtime_config.get("logfile", "")
    if not log_access:
        log_access = legacy_logfile
    if not log_error:
        log_error = legacy_logfile

    built_inbounds = []
    built_inbounds.extend(_build_shadowsocks_inbound(item) for item in shadowsocks_items)
    built_inbounds.append(_build_vmess_inbound(runtime_config, vmess_items))
    built_inbounds.extend(_build_http_inbound(item) for item in http_items)
    built_inbounds.extend(_build_socks5_inbound(item) for item in socks5_items)

    return {
        "log": {
            "access": str(log_access or ""),
            "error": str(log_error or ""),
            "loglevel": str(runtime_config.get("loglevel", "warning")),
        },
        "inbounds": built_inbounds,
        "outbounds": _build_outbounds(config_path, outbound),
        "api": {
            "tag": "api",
            "listen": (
                "127.0.0.1:"
                f"{_require_int(runtime_config.get('api_port'), 'inbounds.config.api_port', 18080)}"
            ),
            "services": ["StatsService"],
        },
        "stats": {},
        "policy": {
            "levels": {
                "0": {
                    "statsUserUplink": True,
                    "statsUserDownlink": True,
                }
            },
            "system": {
                "statsInboundUplink": True,
                "statsInboundDownlink": True,
                "statsOutboundUplink": True,
                "statsOutboundDownlink": True,
            },
        },
    }


def convert(config, _template, output):
    obj = build_config(config)
    with open(output, "w") as output_file:
        print(f"output to file: {output}")
        json.dump(obj, output_file, indent=2)
        output_file.write("\n")


def main():
    parser = argparse.ArgumentParser(description="yaml file to json file")
    parser.add_argument(
        "--log-level",
        help="log level,default level: warn",
        choices=["debug", "info", "warn", "error", "fatal"],
    )
    parser.add_argument("--log-file", help="log file")
    parser.add_argument("--config", help="config file(yaml)", default="config.yaml")
    parser.add_argument(
        "--template",
        help="kept for backward compatibility; no longer used",
        default="tmpl",
    )
    parser.add_argument("--output", help="output json file", default="config.json")
    args = parser.parse_args()

    setup_log(args.log_file, args.log_level)

    try:
        convert(args.config, args.template, args.output)
    except ConfigError as exc:
        raise SystemExit(f"Error: {exc}") from exc


if __name__ == "__main__":
    main()
