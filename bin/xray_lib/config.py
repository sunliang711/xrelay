"""Paths and constants for xray service management."""

import os

_LIB_DIR = os.path.dirname(os.path.realpath(__file__))
BIN_DIR = os.path.dirname(_LIB_DIR)
PROJECT_ROOT = os.path.dirname(BIN_DIR)

ETC_DIR = os.path.join(PROJECT_ROOT, "etc")
APPS_DIR = os.path.join(PROJECT_ROOT, "apps")
YAML2JSON_DIR = os.path.join(PROJECT_ROOT, "yaml2json")
YAML2JSON_VENV_DIR = os.path.join(YAML2JSON_DIR, "venv")
YAML2JSON_PYTHON = os.path.join(YAML2JSON_VENV_DIR, "bin", "python")
YAML2JSON_SCRIPT = os.path.join(YAML2JSON_DIR, "yaml2json.py")
YAML2JSON_REQUIREMENTS = os.path.join(YAML2JSON_DIR, "requirments.txt")
YAML2JSON_TEMPLATE = os.path.join(YAML2JSON_DIR, "tmpl")
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "template")
TRAFFIC_DIR = os.path.join(APPS_DIR, "net-traffic")

XRAY_BIN = "/usr/local/bin/xray"
XRAY_PY = "/usr/local/bin/xray.py"

SERVICE_NAME_TPL = "xray@{}.service"
SYSTEMD_DIR = "/etc/systemd/system"
CLASH_GROUP = "clash"

CRON_BEGIN = "#begin v2relay cron"
CRON_END = "#end v2relay cron"
