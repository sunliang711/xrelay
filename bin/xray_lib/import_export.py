"""Import and export xray instance configs."""

import json
import os
import posixpath
import re
import zipfile
from datetime import datetime, timezone
from typing import Optional

from .config import ETC_DIR
from .log import get_logger
from .utils import ensure_dir

LOGGER = get_logger(__name__)

ARCHIVE_CONFIG_DIR = "configs"
MAX_CONFIG_SIZE = 5 * 1024 * 1024
_NAME_RE = re.compile(r"[A-Za-z0-9_.@-]+")
_YAML_SUFFIXES = (".yaml", ".yml")


def _strip_yaml(name: str) -> str:
    for suffix in _YAML_SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _validate_name(name: str) -> bool:
    if not name:
        LOGGER.error("Instance name is required")
        return False
    if not _NAME_RE.fullmatch(name):
        LOGGER.error(
            "Instance name may only contain letters, numbers, dot, underscore, dash, and @",
        )
        return False
    return True


def _config_paths(name: str) -> tuple[str, str]:
    return (
        os.path.join(ETC_DIR, f"{name}.yaml"),
        os.path.join(ETC_DIR, f"{name}.json"),
    )


def _list_config_names() -> list[str]:
    if not os.path.isdir(ETC_DIR):
        return []
    return sorted(
        os.path.splitext(file_name)[0]
        for file_name in os.listdir(ETC_DIR)
        if file_name.endswith(".yaml")
    )


def _default_export_path() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.abspath(f"xrelay-configs-{timestamp}.zip")


def _resolve_export_names(names: list[str], export_all: bool) -> Optional[list[str]]:
    normalized_names = [_strip_yaml(name) for name in names]
    if export_all and normalized_names:
        LOGGER.error("Use either --all or explicit instance names, not both")
        return None

    selected_names = _list_config_names() if export_all or not normalized_names else normalized_names
    if not selected_names:
        LOGGER.error("No configs found in %s", ETC_DIR)
        return None

    unique_names = []
    seen = set()
    for name in selected_names:
        if name in seen:
            continue
        seen.add(name)
        if not _validate_name(name):
            return None
        yaml_file, _ = _config_paths(name)
        if not os.path.exists(yaml_file):
            LOGGER.error("Config not found: %s", yaml_file)
            return None
        unique_names.append(name)
    return unique_names


def _build_manifest(names: list[str]) -> str:
    manifest = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "configs": [
            {
                "name": name,
                "file": f"{ARCHIVE_CONFIG_DIR}/{name}.yaml",
            }
            for name in names
        ],
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2)


def cmd_export(names: list[str], output: Optional[str], export_all: bool, force: bool) -> int:
    selected_names = _resolve_export_names(names, export_all)
    if selected_names is None:
        return 1

    output_path = os.path.abspath(output) if output else _default_export_path()
    output_dir = os.path.dirname(output_path) or "."
    if not os.path.isdir(output_dir):
        LOGGER.error("Output directory not found: %s", output_dir)
        return 1
    if os.path.exists(output_path) and not force:
        LOGGER.error("Output file already exists: %s", output_path)
        return 1

    LOGGER.info("Exporting %s config(s) to %s", len(selected_names), output_path)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _build_manifest(selected_names))
        for name in selected_names:
            yaml_file, _ = _config_paths(name)
            archive.write(yaml_file, f"{ARCHIVE_CONFIG_DIR}/{name}.yaml")
            LOGGER.info("Added config: %s", name)

    LOGGER.success("Exported %s config(s) to %s", len(selected_names), output_path)
    return 0


def _entry_name(filename: str) -> Optional[str]:
    normalized = posixpath.normpath(filename.replace("\\", "/"))
    parts = normalized.split("/")

    if len(parts) == 1:
        config_file = parts[0]
    elif len(parts) == 2 and parts[0] == ARCHIVE_CONFIG_DIR:
        config_file = parts[1]
    else:
        return None

    if config_file in ("", ".", ".."):
        return None
    if not config_file.endswith(_YAML_SUFFIXES):
        return None
    return _strip_yaml(config_file)


def _read_yaml_file(path: str) -> list[tuple[str, bytes]]:
    name = _strip_yaml(os.path.basename(path))
    with open(path, "rb") as file_obj:
        content = file_obj.read(MAX_CONFIG_SIZE + 1)
    if len(content) > MAX_CONFIG_SIZE:
        LOGGER.error("Config file is too large: %s", path)
        return []
    return [(name, content)]


def _read_zip_file(path: str) -> list[tuple[str, bytes]]:
    configs = []
    seen = set()
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = _entry_name(info.filename)
            if name is None:
                continue
            if name in seen:
                LOGGER.warning("Skipping duplicate config in archive: %s", name)
                continue
            if info.file_size > MAX_CONFIG_SIZE:
                LOGGER.warning("Skipping oversized config in archive: %s", info.filename)
                continue
            seen.add(name)
            configs.append((name, archive.read(info)))
    return configs


def _read_import_configs(path: str) -> Optional[list[tuple[str, bytes]]]:
    if not os.path.exists(path):
        LOGGER.error("Import file not found: %s", path)
        return None

    if path.endswith(_YAML_SUFFIXES):
        return _read_yaml_file(path)

    try:
        return _read_zip_file(path)
    except zipfile.BadZipFile:
        LOGGER.error("Import file is not a valid zip archive: %s", path)
        return None


def cmd_import(path: str) -> int:
    configs = _read_import_configs(os.path.abspath(path))
    if configs is None:
        return 1
    if not configs:
        LOGGER.error("No configs found in import file: %s", path)
        return 1

    ensure_dir(ETC_DIR)
    imported = 0
    skipped = 0
    failed = 0

    for name, content in configs:
        if not _validate_name(name):
            failed += 1
            continue

        yaml_file, json_file = _config_paths(name)
        if os.path.exists(yaml_file) or os.path.exists(json_file):
            LOGGER.info("Skipping existing instance: %s", name)
            skipped += 1
            continue

        try:
            with open(yaml_file, "xb") as file_obj:
                file_obj.write(content)
        except FileExistsError:
            LOGGER.info("Skipping existing instance: %s", name)
            skipped += 1
            continue
        except OSError as exc:
            LOGGER.error("Failed to import %s: %s", name, exc)
            failed += 1
            continue

        imported += 1
        LOGGER.success("Imported config: %s", name)

    LOGGER.info("Import result: imported=%s skipped=%s failed=%s", imported, skipped, failed)
    return 1 if failed else 0
