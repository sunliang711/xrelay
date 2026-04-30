"""Import and export xray instance configs."""

import json
import os
import posixpath
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from typing import Optional

from .config import ETC_DIR
from .log import get_logger
from .utils import ensure_dir

LOGGER = get_logger(__name__)

EXPORT_MANIFEST = "manifest.json"
EXPORT_FORMAT = "xrelay-instance-export"
ARCHIVE_INSTANCE_DIR = "instances"
ARCHIVE_CONFIG_DIR = "configs"
MAX_CONFIG_SIZE = 5 * 1024 * 1024
_NAME_RE = re.compile(r"[A-Za-z0-9_.@-]+")
_YAML_SUFFIXES = (".yaml", ".yml")
_LEGACY_ARCHIVE = object()


def _strip_yaml(name: str) -> str:
    for suffix in _YAML_SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _validate_name(name: str) -> bool:
    if not name:
        LOGGER.error("实例名不能为空")
        return False
    if not _NAME_RE.fullmatch(name):
        LOGGER.error("实例名只能包含字母、数字、点、下划线、连字符和 @")
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
        LOGGER.error("--all 不能和实例名称同时使用")
        return None

    selected_names = _list_config_names() if export_all or not normalized_names else normalized_names
    if not selected_names:
        LOGGER.error("未找到可导出的配置: %s", ETC_DIR)
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
            LOGGER.error("配置不存在: %s", yaml_file)
            return None
        unique_names.append(name)
    return unique_names


def _build_manifest(names: list[str]) -> str:
    manifest = {
        "format": EXPORT_FORMAT,
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "instances": names,
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2)


def cmd_export(names: list[str], output: Optional[str], export_all: bool, force: bool) -> int:
    selected_names = _resolve_export_names(names, export_all)
    if selected_names is None:
        return 1

    output_path = os.path.abspath(output) if output else _default_export_path()
    output_dir = os.path.dirname(output_path) or "."
    if not os.path.isdir(output_dir):
        LOGGER.error("导出目录不存在: %s", output_dir)
        return 1
    if os.path.exists(output_path) and not force:
        LOGGER.error("导出文件已存在: %s", output_path)
        return 1

    LOGGER.info("正在导出 %s 个配置到 %s", len(selected_names), output_path)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(EXPORT_MANIFEST, _build_manifest(selected_names))
        for name in selected_names:
            yaml_file, _ = _config_paths(name)
            archive.write(yaml_file, f"{ARCHIVE_INSTANCE_DIR}/{name}/{name}.yaml")
            LOGGER.info("已加入配置: %s", name)

    LOGGER.success("已导出 %s 个配置到 %s", len(selected_names), output_path)
    return 0


def _zipinfo_is_symlink(info_item: zipfile.ZipInfo) -> bool:
    return ((info_item.external_attr >> 16) & 0o170000) == 0o120000


def _safe_archive_relpath(member_name: str, prefix: str) -> Optional[str]:
    normalized = member_name.replace("\\", "/")
    if not normalized.startswith(prefix):
        return None

    relpath = normalized[len(prefix):]
    if not relpath or relpath.endswith("/"):
        return None

    parts = relpath.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"归档包含不安全路径: {member_name}")
    return posixpath.join(*parts)


def _legacy_entry_name(filename: str) -> Optional[str]:
    normalized = filename.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"归档包含不安全路径: {filename}")

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
        LOGGER.error("配置文件过大: %s", path)
        return []
    return [(name, content)]


def _read_export_manifest(archive: zipfile.ZipFile):
    try:
        raw = archive.read(EXPORT_MANIFEST)
    except KeyError:
        return _LEGACY_ARCHIVE

    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        LOGGER.error("导入文件 manifest.json 格式错误")
        return None

    if "format" not in manifest and isinstance(manifest.get("configs"), list):
        return _LEGACY_ARCHIVE
    if manifest.get("format") != EXPORT_FORMAT or manifest.get("version") != 1:
        LOGGER.error("导入文件格式不受支持")
        return None

    instances = manifest.get("instances")
    if not isinstance(instances, list) or not all(isinstance(name, str) for name in instances):
        LOGGER.error("导入文件实例清单格式错误")
        return None

    return manifest


def _read_manifest_zip_file(archive: zipfile.ZipFile, manifest: dict) -> list[tuple[str, bytes]]:
    configs = []
    for raw_name in manifest["instances"]:
        name = _strip_yaml(raw_name)
        if not _validate_name(name):
            continue

        prefix = f"{ARCHIVE_INSTANCE_DIR}/{name}/"
        members = [item for item in archive.infolist() if item.filename.replace("\\", "/").startswith(prefix)]
        config_member = None
        for member in members:
            if _zipinfo_is_symlink(member):
                raise ValueError(f"归档包含符号链接: {member.filename}")
            relpath = _safe_archive_relpath(member.filename, prefix)
            if relpath == f"{name}.yaml":
                config_member = member

        if config_member is None:
            LOGGER.warning("导入文件中未找到实例 %s 的 YAML 配置，已跳过", name)
            continue
        if config_member.file_size > MAX_CONFIG_SIZE:
            LOGGER.warning("跳过过大的配置文件: %s", config_member.filename)
            continue
        configs.append((name, archive.read(config_member)))
    return configs


def _read_legacy_zip_file(archive: zipfile.ZipFile) -> list[tuple[str, bytes]]:
    configs = []
    seen = set()
    for info in archive.infolist():
        if info.is_dir():
            continue
        if _zipinfo_is_symlink(info):
            raise ValueError(f"归档包含符号链接: {info.filename}")
        name = _legacy_entry_name(info.filename)
        if name is None:
            continue
        if name in seen:
            LOGGER.warning("跳过重复配置: %s", name)
            continue
        if info.file_size > MAX_CONFIG_SIZE:
            LOGGER.warning("跳过过大的配置文件: %s", info.filename)
            continue
        seen.add(name)
        configs.append((name, archive.read(info)))
    return configs


def _read_zip_file(path: str) -> Optional[list[tuple[str, bytes]]]:
    with zipfile.ZipFile(path) as archive:
        manifest = _read_export_manifest(archive)
        if manifest is None:
            return None
        if manifest is _LEGACY_ARCHIVE:
            return _read_legacy_zip_file(archive)
        return _read_manifest_zip_file(archive, manifest)


def _read_import_configs(path: str) -> Optional[list[tuple[str, bytes]]]:
    if not os.path.exists(path):
        LOGGER.error("导入文件不存在: %s", path)
        return None

    if path.endswith(_YAML_SUFFIXES):
        return _read_yaml_file(path)

    try:
        return _read_zip_file(path)
    except zipfile.BadZipFile:
        LOGGER.error("导入文件不是有效的 zip 归档: %s", path)
        return None
    except (OSError, ValueError) as exc:
        LOGGER.error("导入失败: %s", exc)
        return None


def cmd_import(path: str) -> int:
    configs = _read_import_configs(os.path.abspath(path))
    if configs is None:
        return 1
    if not configs:
        LOGGER.error("导入文件中未找到配置: %s", path)
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
            LOGGER.info("实例已存在，跳过: %s", name)
            skipped += 1
            continue

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                delete=False,
                dir=ETC_DIR,
                prefix=f".{name}.import_",
                suffix=".yaml",
            ) as file_obj:
                temp_path = file_obj.name
                file_obj.write(content)
            os.link(temp_path, yaml_file)
            os.chmod(yaml_file, 0o644)
        except FileExistsError:
            LOGGER.info("实例已存在，跳过: %s", name)
            skipped += 1
            continue
        except OSError as exc:
            LOGGER.error("导入 %s 失败: %s", name, exc)
            failed += 1
            continue
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

        imported += 1
        LOGGER.success("已导入配置: %s", name)

    LOGGER.info("导入结果: 新增=%s 跳过=%s 失败=%s", imported, skipped, failed)
    return 1 if failed else 0
