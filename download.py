#!/usr/bin/env python3
"""release 下载脚本

支持按参数下载 mihomo / xray / frp / geoip 的 release。
优先从 GitHub Release 下载，网络不通时自动回退到 Cloudflare R2 镜像。
支持指定版本或自动获取最新版。
"""

import argparse
import gzip
import json
import os
import re
import shutil
import signal
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager

# ── 项目配置 ──────────────────────────────────────────────────────────────

R2_ROOT = "https://pub-06197a088952412f8ff879716ee84855.r2.dev"

PROJECTS = {
    "mihomo": {
        "repo": "MetaCubeX/mihomo",
        "filename_tpl": "mihomo-linux-amd64-compatible-v{version}.gz",
        "r2_path": "mihomo",
        "r2_latest": True,
    },
    "xray": {
        "repo": "XTLS/Xray-core",
        "filename_tpl": "Xray-linux-64.zip",
        "r2_path": "xray",
        "r2_latest": False,
    },
    "frp": {
        "repo": "fatedier/frp",
        "filename_tpl": "frp_{version}_linux_amd64.tar.gz",
        "r2_path": "frp",
        "r2_latest": False,
    },
    "geoip": {
        "repo": "MetaCubeX/meta-rules-dat",
        "filename_tpl": "geoip.metadb",
        "r2_path": "mmdb",
        "r2_latest": True,
        "latest_only": True,
        "github_latest_tag": "latest",
    },
}

TIMEOUT = 15  # 单次操作超时（秒）
SLOW_THRESHOLD = 200 * 1024  # 慢速阈值 200 KB/s，低于此值自动切换源
SLOW_CHECK_AFTER = 10  # 预热秒数，连接建立后等待这么久再判速
PROGRESS_UPDATE_INTERVAL = 0.2  # 进度条刷新间隔（秒）
USER_AGENT = "mihomo-downloader/1.0"


# ── 自定义异常 & SIGALRM 硬超时 ──────────────────────────────────────────

class SlowDownloadError(Exception):
    """下载速度低于阈值"""


def _alarm_handler(signum, frame):
    raise TimeoutError(f"服务器无响应，{TIMEOUT}s 超时中断")


@contextmanager
def _hard_timeout(seconds):
    """设置 SIGALRM 闹钟，超时后强制抛出 TimeoutError"""
    old = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


# ── 工具函数 ──────────────────────────────────────────────────────────────

def fmt_size(n):
    """将字节数格式化为人类可读字符串"""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def print_progress(downloaded, total, start_time):
    """打印下载进度条"""
    elapsed = time.monotonic() - start_time
    speed = downloaded / elapsed if elapsed > 0 else 0

    if total > 0:
        pct = downloaded / total * 100
        bar_w = 30
        filled = int(bar_w * downloaded / total)
        bar = "█" * filled + "░" * (bar_w - filled)
        line = (
            f"\r  [{bar}] {pct:5.1f}%  "
            f"{fmt_size(downloaded)}/{fmt_size(total)}  "
            f"{fmt_size(speed)}/s"
        )
    else:
        line = f"\r  已下载 {fmt_size(downloaded)}  {fmt_size(speed)}/s"

    sys.stdout.write(line)
    sys.stdout.flush()


def strip_archive_suffix(filename):
    """去掉常见压缩包后缀"""
    for suffix in (".tar.gz", ".tgz", ".zip", ".gz"):
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def _ensure_safe_extract_path(base_dir, member_name):
    """确保解压后的路径不会逃出目标目录"""
    base_dir = os.path.abspath(base_dir)
    target_path = os.path.abspath(os.path.join(base_dir, member_name))
    if os.path.commonpath([base_dir, target_path]) != base_dir:
        raise ValueError(f"压缩包内路径不安全: {member_name}")


def _validate_tar_member(base_dir, member):
    """校验 tar 成员路径与类型，拒绝可能逃逸目录的链接与设备文件"""
    _ensure_safe_extract_path(base_dir, member.name)
    if member.issym() or member.islnk():
        raise ValueError(f"tar 成员包含不安全链接: {member.name}")
    if member.isdev():
        raise ValueError(f"tar 成员包含设备文件: {member.name}")


def download(url, dest, min_speed=0):
    """下载文件到 dest，带进度条显示。

    min_speed: 最低平均速度（字节/秒），预热期过后低于此值抛出 SlowDownloadError。
               传 0 表示不限速。
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    try:
        signal.alarm(TIMEOUT)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            start = time.monotonic()
            next_progress_update = start
            buf_size = 65536

            with open(dest, "wb") as f:
                while True:
                    signal.alarm(TIMEOUT)
                    chunk = resp.read(buf_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.monotonic()
                    if now >= next_progress_update or (total > 0 and downloaded >= total):
                        print_progress(downloaded, total, start)
                        next_progress_update = now + PROGRESS_UPDATE_INTERVAL

                    if min_speed > 0:
                        elapsed_so_far = now - start
                        if elapsed_so_far >= SLOW_CHECK_AFTER:
                            avg_speed = downloaded / elapsed_so_far
                            if avg_speed < min_speed:
                                raise SlowDownloadError(
                                    f"平均速度 {fmt_size(avg_speed)}/s "
                                    f"低于阈值 {fmt_size(min_speed)}/s"
                                )
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

    print_progress(downloaded, total, start)
    elapsed = time.monotonic() - start
    speed = downloaded / elapsed if elapsed > 0 else 0
    sys.stdout.write(f"\n  ✓ 完成，共 {fmt_size(downloaded)}，耗时 {elapsed:.1f}s，平均 {fmt_size(speed)}/s\n")
    sys.stdout.flush()


def extract_download(archive_path, output_dir):
    """按文件类型解压下载结果，返回解压后的路径"""
    filename = os.path.basename(archive_path)
    lower_name = filename.lower()

    if lower_name.endswith(".tar.gz") or lower_name.endswith(".tgz"):
        extracted_dir = os.path.join(output_dir, strip_archive_suffix(filename))
        os.makedirs(extracted_dir, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                _validate_tar_member(extracted_dir, member)
            for member in members:
                tar.extract(member, extracted_dir)
        os.remove(archive_path)
        return extracted_dir

    if lower_name.endswith(".zip"):
        extracted_dir = os.path.join(output_dir, strip_archive_suffix(filename))
        os.makedirs(extracted_dir, exist_ok=True)
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.namelist():
                _ensure_safe_extract_path(extracted_dir, member)
            zf.extractall(extracted_dir)
        os.remove(archive_path)
        return extracted_dir

    if lower_name.endswith(".gz"):
        extracted = os.path.join(output_dir, strip_archive_suffix(filename))
        with gzip.open(archive_path, "rb") as fi, open(extracted, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        os.remove(archive_path)
        os.chmod(extracted, 0o755)
        return extracted

    return archive_path


# ── 版本获取 ────────────────────────────────────────────────────────────

def _version_from_api(project):
    """方式 1: GitHub API"""
    api_latest = f"https://api.github.com/repos/{project['repo']}/releases/latest"
    req = urllib.request.Request(api_latest, headers={"User-Agent": USER_AGENT})
    with _hard_timeout(TIMEOUT):
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        data = json.loads(resp.read().decode())
    return data["tag_name"].lstrip("v")


def _version_from_redirect(project):
    """方式 2: GitHub releases/latest 302 重定向，解析最终 URL 中的 tag"""
    releases_latest = f"https://github.com/{project['repo']}/releases/latest"
    req = urllib.request.Request(releases_latest, headers={"User-Agent": USER_AGENT})
    with _hard_timeout(TIMEOUT):
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
    m = re.search(r"/releases/tag/v(.+)$", resp.url)
    if m:
        return m.group(1)
    raise ValueError(f"无法从重定向 URL 解析版本: {resp.url}")


def _version_from_r2(project):
    """方式 3: 从公开 R2 的 latest/.version 文件读取版本号"""
    version_url = f"{R2_ROOT}/{project['r2_path']}/latest/.version"
    req = urllib.request.Request(version_url, headers={"User-Agent": USER_AGENT})
    try:
        with _hard_timeout(TIMEOUT):
            resp = urllib.request.urlopen(req, timeout=TIMEOUT)
            version = resp.read().decode("utf-8").strip()
    except Exception as e:
        raise RuntimeError(f"无法读取 {version_url}: {e}") from e

    if not version:
        raise RuntimeError(f"{version_url} 内容为空")

    return version.lstrip("v")


def get_latest_version(project_name, mode="auto", source=None):
    """按下载模式获取最新版本号，返回 (version, source) 或 (None, None)"""
    project = PROJECTS[project_name]
    github_methods = [
        ("GitHub API", lambda: _version_from_api(project)),
        ("GitHub Redirect", lambda: _version_from_redirect(project)),
    ]
    r2_methods = [("Cloudflare R2", lambda: _version_from_r2(project))]

    if mode == "manual":
        if source == "github":
            methods = github_methods
        elif source == "r2":
            methods = r2_methods
        else:
            raise ValueError(f"不支持的手动下载源: {source}")
    else:
        methods = github_methods + r2_methods

    for name, fn in methods:
        try:
            ver = fn()
            return ver, name
        except Exception as e:
            print(f"  [{name}] 获取失败: {e}")
    return None, None


# ── 主流程 ──────────────────────────────────────────────────────────────


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="下载 mihomo / xray / frp / geoip release（优先 GitHub，回退 Cloudflare R2）"
    )
    parser.add_argument(
        "project",
        choices=sorted(PROJECTS),
        help="要下载的项目",
    )
    parser.add_argument(
        "-v", "--version",
        help="指定版本号，如 1.19.21 / 26.2.4 / 0.68.0（不指定则自动获取最新版）",
    )
    parser.add_argument(
        "-o", "--output",
        default=".",
        help="输出目录，默认当前目录",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="下载后自动解压 .gz / .tar.gz / .zip",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "manual"),
        default="auto",
        help="下载模式：auto 为 GitHub 优先、R2 回退；manual 为只使用指定源",
    )
    parser.add_argument(
        "--source",
        choices=("github", "r2"),
        help="手动模式使用的下载源",
    )
    args = parser.parse_args()

    if args.source and args.mode == "auto":
        args.mode = "manual"
    if args.mode == "manual" and not args.source:
        parser.error("manual 模式必须通过 --source 指定 github 或 r2")

    return args


def make_source(name, url, filename, version=None):
    """构造下载源条目"""
    return {
        "name": name,
        "url": url,
        "filename": filename,
        "version": version,
    }


def build_github_source(project_name, version):
    """构造 GitHub 下载源"""
    project = PROJECTS[project_name]
    filename = build_filename(project, version)
    if project.get("latest_only"):
        github_tag = project.get("github_latest_tag", "latest")
        url = (
            f"https://github.com/{project['repo']}/releases/download/"
            f"{github_tag}/{filename}"
        )
    else:
        url = (
            f"https://github.com/{project['repo']}/releases/download/"
            f"v{version}/{filename}"
        )
    return make_source("GitHub Release", url, filename, version)


def build_r2_latest_source(project_name):
    """构造 R2 当前可用的最新下载源"""
    project = PROJECTS[project_name]
    template = project["filename_tpl"]
    needs_version = "{version}" in template
    r2_version = None

    if needs_version or not project.get("r2_latest"):
        r2_version = _version_from_r2(project)

    filename = build_filename(project, r2_version)
    if project.get("r2_latest"):
        name = "Cloudflare R2 (latest)"
        url = f"{R2_ROOT}/{project['r2_path']}/latest/{filename}"
    else:
        name = "Cloudflare R2 (latest versioned)"
        url = f"{R2_ROOT}/{project['r2_path']}/v{r2_version}/{filename}"

    return make_source(name, url, filename, r2_version)


def build_r2_versioned_source(project_name, version):
    """构造 R2 指定版本下载源"""
    project = PROJECTS[project_name]
    if version is None:
        raise ValueError("R2 指定版本下载源需要明确的版本号")

    filename = build_filename(project, version)
    url = f"{R2_ROOT}/{project['r2_path']}/v{version}/{filename}"
    return make_source("Cloudflare R2 (versioned)", url, filename, version)


def build_sources(project_name, version, is_latest, mode="auto", source=None):
    """根据下载模式构造下载源列表"""
    project = PROJECTS[project_name]

    github_source = build_github_source(project_name, version)

    if mode == "manual":
        if source == "github":
            return [github_source]
        if source == "r2":
            if is_latest:
                return [build_r2_latest_source(project_name)]
            return [build_r2_versioned_source(project_name, version)]
        raise ValueError(f"不支持的手动下载源: {source}")

    sources = [github_source]
    if is_latest:
        try:
            r2_source = build_r2_latest_source(project_name)
        except Exception as e:
            print(f"  [Cloudflare R2] 跳过回退源: {e}")
            return sources

        if version and r2_source["version"] and r2_source["version"] != version:
            print(
                f"  ! GitHub 最新版本为 v{version}，"
                f"但 R2 当前可用版本为 v{r2_source['version']}；"
                "GitHub 失败时将回退到 R2 当前版本。"
            )
        sources.append(r2_source)
        return sources

    sources.append(build_r2_versioned_source(project_name, version))
    return sources


def resolve_version(project_name, project, args):
    """根据项目配置与参数决定要下载的版本"""
    if project.get("latest_only") and args.version:
        print(f"✗ {project_name} 仅支持 latest 下载，不支持指定版本号。")
        return None, True

    version = args.version.lstrip("v") if args.version else None
    is_latest = version is None

    if project.get("latest_only"):
        return None, True

    if not is_latest:
        return version, False

    print(f"正在获取 {project_name} 最新版本号...")
    version, source_name = get_latest_version(project_name, mode=args.mode, source=args.source)
    if version:
        print(f"  ✓ 最新版本: v{version}（来源: {source_name}）")
        return version, True

    if args.mode == "manual":
        print(f"\n✗ 无法从指定源 {args.source} 获取最新版本号。")
    else:
        print("\n✗ 无法自动获取最新版本号（GitHub 与 R2 均不可达）。")
    print(f"请手动指定版本：python download.py {project_name} -v <version>")
    return None, False


def build_filename(project, version):
    """根据项目配置生成下载文件名"""
    template = project["filename_tpl"]
    if "{version}" in template and version is None:
        raise ValueError("当前文件名模板需要版本号，但尚未解析到版本")
    return template.format(version=version) if "{version}" in template else template


def cleanup_partial_download(path):
    """删除失败后残留的部分下载文件"""
    if os.path.exists(path):
        os.remove(path)


def try_sources(sources, output_dir, should_extract):
    """按顺序尝试所有下载源，成功后返回保存路径"""
    for i, source in enumerate(sources):
        is_last = i == len(sources) - 1
        name = source["name"]
        url = source["url"]
        version = source.get("version")
        dest = os.path.join(output_dir, source["filename"])
        print(f"\n{'─' * 60}")
        print(f"尝试源: {name}")
        if version:
            print(f"  版本: v{version}")
        print(f"  URL : {url}")
        try:
            download(url, dest, min_speed=0 if is_last else SLOW_THRESHOLD)
        except SlowDownloadError as e:
            print(f"\n  ✗ 速度过慢，切换下一个源: {e}")
            cleanup_partial_download(dest)
            continue
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
            print(f"  ✗ 失败: {e}")
            cleanup_partial_download(dest)
            continue

        if not should_extract:
            return os.path.abspath(dest)

        print("  正在解压下载内容...")
        extracted = extract_download(dest, output_dir)
        print("  ✓ 解压完成")
        return os.path.abspath(extracted)

    return None


def print_failure_summary(project_name, project, version):
    """打印所有下载源都失败时的提示信息"""
    print(f"\n{'─' * 60}")
    print("✗ 所有下载源均失败，请检查：")
    print("  1. 网络连接是否正常")
    if project.get("latest_only"):
        print(f"  2. {project_name} 的 latest 文件是否存在")
    else:
        print(f"  2. {project_name} 的版本号 v{version} 是否存在")


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    args = parse_args()
    project_name = args.project
    project = PROJECTS[project_name]

    print(f"下载模式: {args.mode}")
    if args.mode == "manual":
        print(f"指定下载源: {args.source}")

    version, is_latest = resolve_version(project_name, project, args)
    if project.get("latest_only") and args.version:
        return 1
    if version is None and not is_latest:
        return 1

    sources = build_sources(project_name, version, is_latest, mode=args.mode, source=args.source)

    os.makedirs(args.output, exist_ok=True)
    saved_path = try_sources(sources, args.output, args.extract)
    if saved_path:
        print(f"\n文件已保存: {saved_path}")
        return 0

    print_failure_summary(project_name, project, version)
    return 1


if __name__ == "__main__":
    sys.exit(main())
