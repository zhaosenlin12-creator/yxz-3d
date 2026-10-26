"""Bambu Studio launcher.

Bambu Studio does not have a well-documented CLI flag. We try a few known
launchers (exe + file arg) and fall back to OS file association.
"""
import os, sys, subprocess, shutil

# Resolve install root dynamically so the same package works from any folder
# on any machine (env override in packaged/started mode).
ROOT = os.environ.get("CARTOON_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG  = os.path.join(ROOT, "logs", "bambu.log")


def _candidate_exes():
    candidates = []
    # 1. Environment variable override (manual set)
    env = os.environ.get("BAMBU_STUDIO_EXE")
    if env:
        candidates.append(env)
    # 2. Standard user-local install
    candidates.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Bambu Studio", "bambu-studio.exe"))
    candidates.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "BambuStudio", "bambu-studio.exe"))
    # 3. Program Files (per-user or system)
    candidates += [
        r"C:\Program Files\Bambu Studio\bambu-studio.exe",
        r"C:\Program Files (x86)\Bambu Studio\bambu-studio.exe",
        r"C:\Program Files\BambuStudio\bambu-studio.exe",
        r"D:\Program Files\Bambu Studio\bambu-studio.exe",
    ]
    # 4. WindowsApps (Microsoft Store install)
    candidates.append(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\bambu-studio.exe"))
    # 5. Registry (HKLM\SOFTWARE\Bambulab\BambuStudio or similar)
    for reg_path, value_name in [
        (r"SOFTWARE\Bambulab\BambuStudio", "InstallPath"),
        (r"SOFTWARE\WOW6432Node\Bambulab\BambuStudio", "InstallPath"),
    ]:
        for hive in ("HKLM", "HKCU"):
            try:
                import winreg
                with winreg.OpenKey(getattr(winreg, hive), reg_path) as k:
                    install_dir, _ = winreg.QueryValueEx(k, value_name)
                    if install_dir:
                        candidates.append(os.path.join(install_dir, "bambu-studio.exe"))
                        candidates.append(install_dir)
            except (FileNotFoundError, OSError):
                continue
            except Exception:
                continue
    # 6. PATH
    for name in ("bambu-studio", "BambuStudio", "bambu-studio.exe"):
        p = shutil.which(name)
        if p:
            candidates.append(p)
    # 7. Common alt name
    candidates.append(r"C:\BambuStudio\bambu-studio.exe")
    # De-dupe + filter existing
    seen = set()
    out = []
    for c in candidates:
        if not c:
            continue
        c = os.path.normpath(c)
        if c in seen:
            continue
        seen.add(c)
        if os.path.isfile(c):
            out.append(c)
    return out


def find_bambu_path():
    """Public: return the bambu-studio.exe path or None."""
    found = _candidate_exes()
    return found[0] if found else None


def open_in_bambu(file_path: str) -> dict:
    """Try to open file_path in Bambu Studio. Returns info dict."""
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    info = {"file": file_path, "method": None, "stdout": "", "stderr": ""}
    exes = _candidate_exes()
    if exes:
        exe = exes[0]
        info["exe"] = exe
        info["method"] = "exe"
        try:
            proc = subprocess.Popen(
                [exe, file_path],
                stdout=open(LOG, "a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
            )
            info["pid"] = proc.pid
            return info
        except Exception as e:
            info["error"] = str(e)
    # Fallback: open with default association (.3mf / .stl)
    try:
        if hasattr(os, "startfile"):
            os.startfile(file_path)
            info["method"] = "os.startfile"
        else:
            subprocess.Popen(["xdg-open", file_path])
            info["method"] = "xdg-open"
        return info
    except Exception as e:
        info["error"] = str(e)
        return info


if __name__ == "__main__":
    fp = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "_smoke_triposr", "mesh.stl")
    print(open_in_bambu(fp))
