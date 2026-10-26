import subprocess, os, shutil, time
print("kill")
subprocess.run(["taskkill", "/F", "/IM", "CartoonPrintStudio.exe", "/T"], capture_output=True)
subprocess.run(["taskkill", "/F", "/IM", "python.exe", "/T"], capture_output=True)
time.sleep(3)
print("wipe")
target = r"C:\kaifa_senlin\delivery_test"
src = r"C:\kaifa_senlin\pingdou\cartoon-print-studio\dist\CartoonPrintStudio"
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
