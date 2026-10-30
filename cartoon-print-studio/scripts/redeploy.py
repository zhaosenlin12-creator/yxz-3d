import subprocess, os, shutil, sys, time
print("kill")
subprocess.run(["taskkill", "/F", "/IM", "CartoonPrintStudio.exe", "/T"], capture_output=True)
subprocess.run(["taskkill", "/F", "/IM", "python.exe", "/T"], capture_output=True)
time.sleep(3)
print("wipe")
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "dist", "delivery_test")
src = os.path.join(root, "dist", "CartoonPrintStudio")
if os.path.isdir(target):
    shutil.rmtree(target)
os.makedirs(target)
print("mirror")
r = subprocess.run(["robocopy", src, target, "/MIR", "/NJH", "/NJS", "/NDL", "/NFL"], capture_output=True, text=True)
print("rc:", r.returncode)
print("contents:")
for f in sorted(os.listdir(target)):
    full = os.path.join(target, f)
    sz = os.path.getsize(full) if os.path.isfile(full) else "dir"
    print(" ", f, sz)
