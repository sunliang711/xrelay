"""Paths and constants for xray service management."""

import os

_LIB_DIR = os.path.dirname(os.path.realpath(__file__))
BIN_DIR = os.path.dirname(_LIB_DIR)
PROJECT_ROOT = os.path.dirname(BIN_DIR)

ETC_DIR = os.path.join(PROJECT_ROOT, "etc")
APPS_DIR = os.path.join(PROJECT_ROOT, "apps")
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "template")
TRAFFIC_DIR = os.path.join(APPS_DIR, "net-traffic")

XRAY_BIN = "/usr/local/bin/xray"
XRAY_PY = "/usr/local/bin/xray.py"

GENFRONTEND_DIR = os.path.join(APPS_DIR, "genfrontend")
GENFRONTEND_BIN = os.path.join(GENFRONTEND_DIR, "genfrontend")
GENFRONTEND_TPL = os.path.join(GENFRONTEND_DIR, "frontendTemplate")

SERVICE_NAME_TPL = "xray@{}.service"
SYSTEMD_DIR = "/etc/systemd/system"
CLASH_GROUP = "clash"

CRON_BEGIN = "#begin v2relay cron"
CRON_END = "#end v2relay cron"
