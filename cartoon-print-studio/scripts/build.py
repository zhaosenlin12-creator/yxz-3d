import subprocess, os, shutil, time, pathlib, sys

# Resolve the project root from this script so a build always packages the
# checkout it was started from.
root = str(pathlib.Path(__file__).resolve().parent.parent)
pyexe = os.path.join(root, "ai", "forge-webui", "venv", "Scripts", "python.exe")
if not os.path.isfile(pyexe):
    pyexe = sys.executable

# Clean
for d in ("dist", "build"):
    p = os.path.join(root, d)
    if os.path.isdir(p):
        shutil.rmtree(p)
        print("removed", p)

# Build
os.makedirs(os.path.join(root, "logs"), exist_ok=True)
log = open(os.path.join(root, "logs", "build5.log"), "ab", buffering=0)
proc = subprocess.Popen([pyexe, "-m", "PyInstaller", "--noconfirm", "--clean",
                         os.path.join(root, "installer", "run.spec")],
                        cwd=root, stdout=log, stderr=log)
print("PyInstaller pid", proc.pid)
rc = proc.wait()
print("PyInstaller exit", rc)
print("Done. tail:")
time.sleep(0.5)
import pathlib
p = pathlib.Path(os.path.join(root, "logs", "build5.log"))
print(p.read_text(encoding="utf-8", errors="ignore")[-2000:])
