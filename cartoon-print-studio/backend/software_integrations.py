"""Safe Windows integration helpers for 宜小智 exports.

Detection is read-only. Opening a file is explicit and never starts a print job;
the selected desktop application remains responsible for slicing/cutting and
the user must confirm the final operation there.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


def _data_dir() -> Path:
    """Where the local app keeps its mutable state (project store, settings)."""
    env = os.environ.get("CARTOON_DATA_DIR")
    if env:
        return Path(env)
    root = os.environ.get("CARTOON_ROOT") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
    return Path(root) / "data"


OVERRIDE_FILE = "software_paths.json"

# Resolving the Start Menu / Desktop shortcuts goes through COM and takes
# roughly ten seconds on Windows. The set of installed tools rarely changes
# between two panel openings, so the discovery is cached for a short while.
# Overrides and file existence are still evaluated on every call, so a tool
# the user just installed or re-pointed shows up immediately.
DISCOVERY_TTL_SECONDS = 300
_discovery_cache: dict[str, Any] = {"expires_at": 0.0, "value": None}
_discovery_lock = threading.Lock()


def _override_path() -> Path:
    return _data_dir() / OVERRIDE_FILE


def load_overrides() -> dict[str, str]:
    """Read the user-corrected executable paths, ignoring a broken file."""
    path = _override_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in data.items()
        if isinstance(key, str) and isinstance(value, str) and value.strip()
    }


def save_override(tool_id: str, executable: str) -> dict[str, str]:
    """Persist a user-corrected executable path and return the new mapping."""
    overrides = load_overrides()
    overrides[tool_id] = executable
    path = _override_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(overrides, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return overrides


def clear_override(tool_id: str) -> dict[str, str]:
    """Forget a user-corrected path so automatic detection takes over again."""
    overrides = load_overrides()
    overrides.pop(tool_id, None)
    path = _override_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(overrides, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return overrides


def _existing(candidates: list[str]) -> str | None:
    seen: set[str] = set()
    for raw in candidates:
        if not raw:
            continue
        path = os.path.normpath(os.path.expandvars(raw))
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        if os.path.isfile(path):
            return path
    return None


def _glob_candidates(patterns: list[str]) -> list[str]:
    result: list[str] = []
    for pattern in patterns:
        result.extend(str(item) for item in Path(os.path.expandvars(pattern)).parent.glob(Path(pattern).name))
    return result


def _windows_registry_candidates() -> dict[str, list[str]]:
    """Read known install locations from Windows registry, when available."""
    result = {"bambu": [], "xtool": []}
    try:
        import winreg
    except ImportError:
        return result

    locations = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"),
    )
    app_paths = {
        "bambu": ("bambu-studio.exe",),
        "xtool": ("xToolStudio.exe", "xTool.exe", "xtool-studio.exe"),
    }
    for hive, root in locations:
        for tool_id, names in app_paths.items():
            for name in names:
                try:
                    with winreg.OpenKey(hive, root + "\\" + name) as key:
                        value, _ = winreg.QueryValueEx(key, None)
                        result[tool_id].append(str(value).strip('"'))
                except OSError:
                    pass

    uninstall_roots = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, root in uninstall_roots:
        try:
            with winreg.OpenKey(hive, root) as parent:
                subkeys = [winreg.EnumKey(parent, index) for index in range(winreg.QueryInfoKey(parent)[0])]
        except OSError:
            continue
        for subkey in subkeys:
            try:
                with winreg.OpenKey(hive, root + "\\" + subkey) as key:
                    display_name = str(winreg.QueryValueEx(key, "DisplayName")[0]).lower()
                    tool_id = "bambu" if "bambu studio" in display_name else "xtool" if "xtool studio" in display_name else None
                    if not tool_id:
                        continue
                    for value_name in ("DisplayIcon", "InstallLocation"):
                        try:
                            value = str(winreg.QueryValueEx(key, value_name)[0]).strip().strip('"').split(",", 1)[0]
                        except OSError:
                            continue
                        if value.lower().endswith(".exe"):
                            result[tool_id].append(value)
                        else:
                            executable_names = ("bambu-studio.exe",) if tool_id == "bambu" else app_paths["xtool"]
                            result[tool_id].extend(os.path.join(value, exe) for exe in executable_names)
            except OSError:
                continue
    return result


def _shortcut_candidates() -> dict[str, list[str]]:
    """Resolve matching Desktop/Start Menu shortcuts without requiring COM."""
    result = {"bambu": [], "xtool": []}
    roots = (
        os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
        os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.environ.get("ProgramData", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.environ.get("PUBLIC", ""), "Desktop"),
    )
    try:
        from win32com.client import Dispatch
    except (ImportError, OSError):
        return result
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        try:
            shortcuts = Path(root).rglob("*.lnk")
            for shortcut in shortcuts:
                name = shortcut.stem.lower()
                tool_id = "bambu" if "bambu" in name else "xtool" if "xtool" in name else None
                if not tool_id:
                    continue
                try:
                    target = Dispatch("WScript.Shell").CreateShortcut(str(shortcut)).TargetPath
                    if target:
                        result[tool_id].append(str(target))
                except Exception:
                    continue
        except OSError:
            continue
    return result


def _cached_discovery() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Registry + shortcut lookup, memoised for a few minutes.

    Both lookups touch COM and the Windows registry, which costs about ten
    seconds per call. Caching keeps the "open with software" panel responsive
    when the user opens it more than once.
    """
    now = time.monotonic()
    with _discovery_lock:
        cached = _discovery_cache["value"]
        if cached is not None and _discovery_cache["expires_at"] > now:
            return cached
    registry = _windows_registry_candidates()
    shortcuts = _shortcut_candidates()
    with _discovery_lock:
        _discovery_cache["value"] = (registry, shortcuts)
        _discovery_cache["expires_at"] = time.monotonic() + DISCOVERY_TTL_SECONDS
    return registry, shortcuts


def detect_software() -> list[dict[str, Any]]:
    """Return known local tools, with an executable path only when installed."""
    local = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\\Program Files (x86)")
    registry, shortcuts = _cached_discovery()
    overrides = load_overrides()
    # ``formats`` are the formats the tool accepts; ``verified`` are the ones
    # this machine has actually opened successfully. The UI only advertises
    # verified formats, so an unproven claim (Bambu Studio has no GLB
    # importer, for instance) never reaches the user.
    definitions: list[tuple[str, str, str, list[str], tuple[str, ...], tuple[str, ...]]] = [
        ("bambu", "Bambu Studio", "3d-print", [
            os.environ.get("BAMBU_STUDIO_EXE", ""),
            rf"{local}\Programs\Bambu Studio\bambu-studio.exe",
            rf"{program_files}\Bambu Studio\bambu-studio.exe",
            rf"{program_files_x86}\Bambu Studio\bambu-studio.exe",
            *registry.get("bambu", []),
            *shortcuts.get("bambu", []),
        ], ("stl", "obj"), ("stl",)),
        ("orca", "OrcaSlicer", "3d-print", [
            rf"{local}\Programs\OrcaSlicer\orca-slicer.exe",
            rf"{program_files}\OrcaSlicer\orca-slicer.exe",
            rf"{program_files_x86}\OrcaSlicer\orca-slicer.exe",
            shutil.which("orca-slicer") or "",
        ], ("stl", "obj", "3mf"), ()),
        ("prusa", "PrusaSlicer", "3d-print", [
            rf"{local}\Programs\Prusa3D\PrusaSlicer\prusa-slicer.exe",
            rf"{program_files}\Prusa3D\PrusaSlicer\prusa-slicer.exe",
            shutil.which("prusa-slicer") or "",
        ], ("stl", "obj", "3mf"), ()),
        ("cura", "UltiMaker Cura", "3d-print", [
            *_glob_candidates([rf"{program_files}\UltiMaker Cura*\UltiMaker-Cura.exe", rf"{local}\Programs\UltiMaker Cura*\UltiMaker-Cura.exe"]),
            shutil.which("UltiMaker-Cura") or "",
        ], ("stl", "obj"), ()),
        ("blender", "Blender", "3d-edit", [
            *_glob_candidates([rf"{program_files}\Blender Foundation\Blender*\blender.exe", rf"{local}\Programs\Blender Foundation\Blender*\blender.exe"]),
            shutil.which("blender") or "",
        ], ("glb", "obj", "stl"), ()),
        ("lightburn", "LightBurn", "laser", [
            rf"{program_files}\LightBurn\LightBurn.exe",
            rf"{program_files_x86}\LightBurn\LightBurn.exe",
            rf"{local}\LightBurn\LightBurn.exe",
            shutil.which("LightBurn") or "",
        ], ("svg", "dxf", "png"), ()),
        ("lasergrbl", "LaserGRBL", "laser", [
            rf"{program_files}\LaserGRBL\LaserGRBL.exe",
            rf"{program_files_x86}\LaserGRBL\LaserGRBL.exe",
            shutil.which("LaserGRBL") or "",
        ], ("svg", "png"), ()),
        ("xtool", "xTool Studio", "laser", [
            os.environ.get("XTOOL_STUDIO_EXE", ""),
            rf"{local}\Programs\xTool Studio\xToolStudio.exe",
            rf"{program_files}\xTool\xTool Studio\xToolStudio.exe",
            rf"{program_files_x86}\xTool\xTool Studio\xToolStudio.exe",
            *registry.get("xtool", []),
            *shortcuts.get("xtool", []),
        ], ("png", "svg"), ("png", "svg")),
    ]
    tools: list[dict[str, Any]] = []
    for tool_id, name, kind, candidates, formats, verified in definitions:
        override = overrides.get(tool_id, "")
        if override:
            path = override if os.path.isfile(override) else None
        else:
            path = _existing(candidates)
        tools.append({
            "id": tool_id,
            "name": name,
            "kind": kind,
            "available": bool(path),
            "path": path,
            "formats": list(formats),
            "verifiedFormats": list(verified),
            "overridden": bool(override),
            "override": override,
            "overrideMissing": bool(override) and not os.path.isfile(override),
        })
    return tools


def open_export(executable: str, file_path: str, tool_id: str = "") -> dict[str, Any]:
    """Open an export in a selected application, without printing/cutting.

    ``tool_id`` selects the launch strategy:

    * cli   – the app accepts the file as a positional argument (Orca,
              PrusaSlicer, Cura, Blender, LightBurn, LaserGRBL). The file is
              loaded directly into the app.
    * manual – Bambu Studio and xTool Studio ignore file arguments (verified
              on 2026-10-27). For them we start the app, then reveal the file
              in Explorer (`explorer /select,`) so the user can drag it in or
              paste the copied path in the app's import dialog. The path is
              also returned so the UI can copy it to the clipboard.
    """
    if not executable or not os.path.isfile(executable):
        raise FileNotFoundError("所选软件未安装或路径已失效")
    if not file_path or not os.path.isfile(file_path):
        raise FileNotFoundError("导出文件还没有生成")
    no_cli = {"bambu", "xtool"}
    method = "manual" if tool_id in no_cli else "cli"
    if method == "cli":
        try:
            process = subprocess.Popen([executable, file_path], close_fds=True)
        except OSError as exc:
            raise RuntimeError(f"打开软件失败：{exc}") from exc
        return {
            "ok": True, "pid": process.pid, "executable": executable, "file": file_path,
            "method": method,
            "message": "已打开软件并加载文件，请确认参数后继续。",
        }
    # manual: start the app, then reveal the file for drag-in / paste.
    try:
        subprocess.Popen([executable], close_fds=True)
    except OSError as exc:
        raise RuntimeError(f"打开软件失败：{exc}") from exc
    folder = os.path.dirname(file_path)
    revealed = False
    if os.path.isdir(folder):
        try:
            subprocess.Popen(["explorer", "/select,", file_path], close_fds=True)
            revealed = True
        except OSError:
            revealed = False
    return {
        "ok": True, "executable": executable, "file": file_path,
        "method": method, "revealed": revealed,
        "message": "软件已打开。该软件不支持命令行自动导入文件，已为您定位文件并复制路径：请在软件中点击导入/上传后粘贴路径（或直接拖入）。",
    }
