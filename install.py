#!/usr/bin/env python3
"""Install / uninstall xray environment.

Steps performed by ``install``:
  1. Download xray release via download.py → install binary to /usr/local/bin
  2. Install genfrontend (via existing shell script)
  3. Create the ``clash`` system group (if absent)
  4. Symlink bin/xray.py → /usr/local/bin/xray.py
  5. Generate and install the systemd template unit xray@.service
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.realpath(__file__))

XRAY_BIN_DEST = "/usr/local/bin/xray"
XRAY_PY_SRC = os.path.join(PROJECT_ROOT, "bin", "xray.py")
XRAY_PY_DEST = "/usr/local/bin/xray.py"
DOWNLOAD_PY = os.path.join(PROJECT_ROOT, "download.py")
APPS_DIR = os.path.join(PROJECT_ROOT, "apps")
ETC_DIR = os.path.join(PROJECT_ROOT, "etc")
TEMPLATE_SRC = os.path.join(PROJECT_ROOT, "template", "xray@.service")
SYSTEMD_DIR = "/etc/systemd/system"
CLASH_GROUP = "clash"


# ── helpers ──────────────────────────────────────────────────────────────


def _run_root(*args, check=True):
    cmd = list(args) if os.getuid() == 0 else ["sudo"] + list(args)
    print(f"[Running]: {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def _require_linux():
    if platform.system() != "Linux":
        sys.exit("Error: this installer requires Linux.")


def _require_commands(*cmds):
    missing = [c for c in cmds if not shutil.which(c)]
    if missing:
        sys.exit(f"Error: missing required commands: {', '.join(missing)}")


# ── install stages ───────────────────────────────────────────────────────


def _install_xray():
    print("\n=== Installing xray ===")
    tmp_dir = "/tmp/xray-install"
    os.makedirs(tmp_dir, exist_ok=True)

    subprocess.run(
        [sys.executable, DOWNLOAD_PY, "xray", "-o", tmp_dir, "--extract"],
        check=True,
    )

    xray_binary = None
    for root, _dirs, files in os.walk(tmp_dir):
        if "xray" in files:
            candidate = os.path.join(root, "xray")
            if os.access(candidate, os.X_OK):
                xray_binary = candidate
                break

    if not xray_binary:
        sys.exit("Error: xray binary not found after extraction")

    _run_root("cp", xray_binary, XRAY_BIN_DEST)
    _run_root("chmod", "755", XRAY_BIN_DEST)

    xray_dir = os.path.dirname(xray_binary)
    for dat in ("geoip.dat", "geosite.dat"):
        src = os.path.join(xray_dir, dat)
        if os.path.exists(src):
            _run_root("cp", src, os.path.join("/usr/local/bin", dat))

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"xray installed → {XRAY_BIN_DEST}")


def _install_genfrontend():
    print("\n=== Installing genfrontend ===")
    script = os.path.join(PROJECT_ROOT, "scripts", "installGenfrontend.sh")
    if os.path.exists(script):
        subprocess.run(["bash", script, "install", APPS_DIR], check=True)
    else:
        print("Warning: genfrontend install script not found, skipping.")


def _add_group():
    print("\n=== Setting up group ===")
    result = subprocess.run(
        ["getent", "group", CLASH_GROUP], capture_output=True
    )
    if result.returncode == 0:
        print(f"Group '{CLASH_GROUP}' already exists, skip.")
        return
    _run_root("groupadd", CLASH_GROUP)
    print(f"Group '{CLASH_GROUP}' created.")


def _install_xray_py():
    print("\n=== Symlinking xray.py ===")
    os.chmod(XRAY_PY_SRC, 0o755)
    if os.path.exists(XRAY_PY_DEST) or os.path.islink(XRAY_PY_DEST):
        _run_root("rm", "-f", XRAY_PY_DEST)
    _run_root("ln", "-s", XRAY_PY_SRC, XRAY_PY_DEST)
    print(f"  {XRAY_PY_SRC} → {XRAY_PY_DEST}")


def _install_systemd_template():
    print("\n=== Installing systemd template ===")
    if not os.path.exists(TEMPLATE_SRC):
        sys.exit(f"Error: template not found: {TEMPLATE_SRC}")

    with open(TEMPLATE_SRC) as f:
        content = f.read()

    content = (
        content
        .replace("<XRAY_PY>", XRAY_PY_DEST)
        .replace("<XRAY_BIN>", XRAY_BIN_DEST)
        .replace("<ETC_DIR>", ETC_DIR)
        .replace("<GROUP>", CLASH_GROUP)
    )

    tmp = "/tmp/xray@.service"
    with open(tmp, "w") as f:
        f.write(content)

    dest = os.path.join(SYSTEMD_DIR, "xray@.service")
    _run_root("mv", tmp, dest)
    _run_root("systemctl", "daemon-reload")
    print(f"  Installed {dest}")


# ── uninstall ────────────────────────────────────────────────────────────


def _uninstall():
    print("\n=== Uninstalling ===")

    if os.path.isdir(ETC_DIR):
        configs = [f[:-5] for f in os.listdir(ETC_DIR) if f.endswith(".yaml")]
        for name in configs:
            svc = f"xray@{name}.service"
            _run_root("systemctl", "stop", svc, check=False)
            _run_root("systemctl", "disable", svc, check=False)

    template = os.path.join(SYSTEMD_DIR, "xray@.service")
    if os.path.exists(template):
        _run_root("rm", "-f", template)
        _run_root("systemctl", "daemon-reload")

    for p in (XRAY_BIN_DEST, XRAY_PY_DEST):
        if os.path.exists(p) or os.path.islink(p):
            _run_root("rm", "-f", p)

    for dat in ("geoip.dat", "geosite.dat"):
        p = os.path.join("/usr/local/bin", dat)
        if os.path.exists(p):
            _run_root("rm", "-f", p)

    for sub in ("genfrontend", "xray"):
        d = os.path.join(APPS_DIR, sub)
        if os.path.isdir(d):
            shutil.rmtree(d)

    print("Uninstall complete.")


# ── entry ────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="xray installer")
    parser.add_argument(
        "action", choices=["install", "uninstall"],
        help="install or uninstall xray",
    )
    args = parser.parse_args()

    _require_linux()

    if args.action == "install":
        _require_commands("iptables", "python3")
        os.makedirs(ETC_DIR, exist_ok=True)

        _install_xray()
        _install_genfrontend()
        _add_group()
        _install_xray_py()
        _install_systemd_template()

        print(f"""
{'=' * 60}
Installation complete!

  xray binary      : {XRAY_BIN_DEST}
  xray.py CLI      : {XRAY_PY_DEST}
  config directory  : {ETC_DIR}
  systemd template  : {SYSTEMD_DIR}/xray@.service

Usage:
  xray.py add   <name>     Create a new config
  xray.py start <name>     Start   → systemctl start xray@<name>.service
  xray.py stop  <name>     Stop    → systemctl stop  xray@<name>.service
  xray.py list             List configs
  xray.py log   <name>     Follow journal
{'=' * 60}""")

    elif args.action == "uninstall":
        _uninstall()

    return 0


if __name__ == "__main__":
    sys.exit(main())
