# -*- coding: utf-8 -*-
"""
WebUI frontend asset preparation helper.

Default behavior runs startup-time frontend auto build.
Set WEBUI_AUTO_BUILD=false to disable auto build and only verify artifacts.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

logger = logging.getLogger(__name__)

_FALSEY_ENV_VALUES = {"0", "false", "no", "off"}
_BUILD_INPUT_FILES = (
    "package.json",
    "package-lock.json",
    "vite.config.ts",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
    "eslint.config.js",
    "postcss.config.js",
    "tailwind.config.js",
    "index.html",
)
_BUILD_INPUT_DIRS = ("src", "public")


def _is_truthy_env(var_name: str, default: str = "true") -> bool:
    """解析常見的環境變量真值/假值表達（大小寫不敏感）。"""
    value = os.getenv(var_name, default).strip().lower()
    return value not in _FALSEY_ENV_VALUES


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _tree_latest_mtime(root: Path) -> float:
    if not root.exists():
        return 0.0
    latest = 0.0
    try:
        for p in root.rglob("*"):
            if p.is_file():
                latest = max(latest, _safe_mtime(p))
    except OSError:
        # Fallback to root mtime when recursive traversal fails on restricted envs.
        latest = max(latest, _safe_mtime(root))
    return latest


def _max_mtime(paths: Iterable[Path]) -> float:
    latest = 0.0
    for path in paths:
        latest = max(latest, _safe_mtime(path))
    return latest


def _resolve_artifact_index(frontend_dir: Path) -> Path:
    # Prefer static/index.html because it is the configured output path in this repo.
    static_index = (frontend_dir / ".." / ".." / "static" / "index.html").resolve()
    dist_index = frontend_dir / "dist" / "index.html"
    build_index = frontend_dir / "build" / "index.html"
    if static_index.exists():
        return static_index

    fallback_candidates = [p for p in (dist_index, build_index) if p.exists()]
    if not fallback_candidates:
        return static_index
    return max(fallback_candidates, key=_safe_mtime)


def _needs_dependency_install(frontend_dir: Path, package_json: Path, lock_file: Path, force_build: bool) -> bool:
    node_modules_dir = frontend_dir / "node_modules"
    install_marker = node_modules_dir / ".package-lock.json"
    deps_marker_mtime = _safe_mtime(install_marker) if install_marker.exists() else _safe_mtime(node_modules_dir)
    deps_input_mtime = _max_mtime((package_json, lock_file))
    return force_build or (not node_modules_dir.exists()) or (deps_marker_mtime < deps_input_mtime)


def _collect_build_inputs_latest_mtime(frontend_dir: Path) -> float:
    latest = _max_mtime(frontend_dir / filename for filename in _BUILD_INPUT_FILES)
    for dirname in _BUILD_INPUT_DIRS:
        latest = max(latest, _tree_latest_mtime(frontend_dir / dirname))
    return latest


def _needs_frontend_build(frontend_dir: Path, force_build: bool) -> tuple[bool, Path]:
    artifact_index = _resolve_artifact_index(frontend_dir)
    inputs_latest_mtime = _collect_build_inputs_latest_mtime(frontend_dir)
    artifact_mtime = _safe_mtime(artifact_index)
    needs_build = force_build or (not artifact_index.exists()) or (artifact_mtime < inputs_latest_mtime)
    return needs_build, artifact_index


def _run_frontend_commands(commands: Sequence[Sequence[str]], frontend_dir: Path) -> bool:
    try:
        for command in commands:
            logger.info("執行前端命令: %s", " ".join(command))
            subprocess.run(command, cwd=frontend_dir, check=True)
        logger.info("前端靜態資源構建完成")
        return True
    except subprocess.CalledProcessError as exc:
        cmd_display = " ".join(exc.cmd) if isinstance(exc.cmd, (list, tuple)) else str(exc.cmd)
        logger.error(
            "前端命令執行失敗（exit_code=%s）: %s",
            getattr(exc, "returncode", "N/A"),
            cmd_display,
        )
        return False


def _manual_build_command(frontend_dir: Path) -> str:
    lock_file = frontend_dir / "package-lock.json"
    install_cmd = "npm ci" if lock_file.exists() else "npm install"
    return f'cd "{frontend_dir}" && {install_cmd} && npm run build'


def _has_static_assets(static_dir: Path) -> bool:
    """檢查 static/assets/ 是否存在且包含 CSS/JS 文件。

    index.html 存在但 assets/ 爲空或缺失時，瀏覽器無法加載樣式與腳本，
    會導致頁面元素異常放大、布局錯亂（純裸 HTML 渲染）。
    """
    assets_dir = static_dir / "assets"
    if not assets_dir.is_dir():
        return False
    try:
        return any(
            f.suffix in (".js", ".css") and f.is_file()
            for f in assets_dir.iterdir()
        )
    except OSError:
        return False


def _warn_if_assets_missing(artifact_index: Path, frontend_dir: Path) -> None:
    """當 index.html 存在但 assets/ 缺失時，發出頁面顯示異常警告。"""
    static_dir = artifact_index.parent
    assets_dir = static_dir / "assets"
    if not _has_static_assets(static_dir):
        logger.warning(
            "檢測到 %s 但 %s 目錄不存在或無 CSS/JS 文件，"
            "WebUI 將因缺少樣式與腳本而顯示異常（元素過大、布局錯亂）",
            artifact_index,
            assets_dir,
        )
        logger.warning(
            "請重新構建前端以修復此問題: %s",
            _manual_build_command(frontend_dir),
        )
        logger.warning(
            "Docker 用戶請執行: docker-compose -f ./docker/docker-compose.yml build --no-cache"
        )


def prepare_webui_frontend_assets() -> bool:
    """
    Prepare frontend assets for WebUI startup.

    Default mode (WEBUI_AUTO_BUILD=true):
    - Run npm install/build when dependencies or sources changed,
      or artifacts are missing.

    Manual mode (WEBUI_AUTO_BUILD=false):
    - Do not compile frontend during backend startup.
    - Only check whether existing artifacts are available.
    """
    frontend_dir = Path(__file__).resolve().parent.parent / "apps" / "dsa-web"
    auto_build_enabled = _is_truthy_env("WEBUI_AUTO_BUILD", "true")
    artifact_index = _resolve_artifact_index(frontend_dir)

    if not auto_build_enabled:
        if artifact_index.exists():
            logger.info("WEBUI_AUTO_BUILD=false，檢測到前端靜態產物: %s", artifact_index)
            _warn_if_assets_missing(artifact_index, frontend_dir)
            return True
        logger.warning("未檢測到 WebUI 前端靜態產物: %s", artifact_index)
        logger.warning("當前配置 WEBUI_AUTO_BUILD=false，不會在後端啓動時自動編譯前端")
        logger.warning("請先手動構建前端: %s", _manual_build_command(frontend_dir))
        logger.warning("如需啓動時自動構建，可設置 WEBUI_AUTO_BUILD=true")
        return False

    force_build = _is_truthy_env("WEBUI_FORCE_BUILD", "false")
    needs_build, artifact_index = _needs_frontend_build(frontend_dir=frontend_dir, force_build=force_build)

    if not needs_build:
        logger.info("檢測到可直接復用的前端靜態產物，跳過運行時自動構建: %s", artifact_index)
        _warn_if_assets_missing(artifact_index, frontend_dir)
        return True

    package_json = frontend_dir / "package.json"
    if not package_json.exists():
        logger.warning("未找到前端項目，無法自動構建: %s", package_json)
        logger.warning("可先手動檢查前端目錄或關閉 WEBUI_AUTO_BUILD")
        return False

    npm_path = shutil.which("npm")
    if not npm_path:
        logger.warning("未檢測到 npm，無法自動構建前端")
        logger.warning("請先手動構建前端靜態資源: %s", _manual_build_command(frontend_dir))
        return False

    lock_file = frontend_dir / "package-lock.json"
    needs_install = _needs_dependency_install(
        frontend_dir=frontend_dir,
        package_json=package_json,
        lock_file=lock_file,
        force_build=force_build,
    )

    commands = []
    if needs_install:
        lock_exists = (frontend_dir / "package-lock.json").exists()
        commands.append([npm_path, "ci" if lock_exists else "install"])
    if needs_build:
        commands.append([npm_path, "run", "build"])

    logger.info(
        "前端構建檢查結果: needs_install=%s, needs_build=%s, artifact=%s",
        needs_install,
        needs_build,
        artifact_index,
    )
    return _run_frontend_commands(commands=commands, frontend_dir=frontend_dir)
