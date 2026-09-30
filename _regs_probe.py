import os, socket, subprocess, sys, time

ROOT = r"F:\boruix-project"
q = None
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    if line.startswith("QEMU_DIR="):
        q = line.strip().split("=", 1)[1]
exe = os.path.join(q, "qemu-system-x86_64.exe")
fw = os.path.join(q, "share", "edk2-x86_64-code.fd")
SLOG = os.path.join(ROOT, "_b2_sysdisk_serial.log")
PORT = 45485
if os.path.exists(SLOG):
    os.remove(SLOG)
qemu = [exe, "-m", "256", "-smp", "4", "-display", "none", "-no-reboot",
        "-serial", "file:" + SLOG,
        "-monitor", "tcp:127.0.0.1:%d,server=on,wait=off" % PORT,
        "-drive", "format=raw,file=" + os.path.join(ROOT, "systemdisk.img"),
        "-drive", "if=pflash,format=raw,readonly=on,file=" + fw,
        "-drive", "format=raw,file=fat:rw:" + os.path.join(ROOT, "esp-liftoff")]
p = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def wait_log(pat, timeout):
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            with open(SLOG, "rb") as h:
                if pat.encode() in h.read():
                    return True
        except OSError:
            pass
        time.sleep(1.0)
    return False

spawned = wait_log("spawned pid=1", 420)
print("spawned seen:", spawned)
time.sleep(3.0)
s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
time.sleep(1.0)
try:
    s.recv(65536)
except OSError:
    pass
s.sendall(b"info registers -a\n")
time.sleep(2.0)
s.settimeout(3.0)
out = b""
try:
    while True:
        c = s.recv(65536)
        if not c:
            break
        out += c
        if b"(qemu)" in out[-20:]:
            break
except socket.timeout:
    pass
p.kill()
txt = out.decode("utf-8", "replace")
open(os.path.join(ROOT, "_regs.txt"), "w", encoding="utf-8").write(txt)
print("regs bytes:", len(out))
# 提取每个 CPU 的 RIP 与 CR3
import re
for m in re.finditer(r"CPU #(\d+)", txt):
    pass
print(txt[:3000])
