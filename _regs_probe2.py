import os, socket, subprocess, sys, time

ROOT = r"F:\boruix-project"
q = None
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    if line.startswith("QEMU_DIR="):
        q = line.strip().split("=", 1)[1]
exe = os.path.join(q, "qemu-system-x86_64.exe")
fw = os.path.join(q, "share", "edk2-x86_64-code.fd")
SLOG = os.path.join(ROOT, "_b2_sysdisk_serial.log")
PORT = 45486
if os.path.exists(SLOG):
    os.remove(SLOG)
qemu = [exe,
        "-hda", os.path.join(ROOT, "systemdisk.img"),
        "-hdb", os.path.join(ROOT, "disk.img"),
        "-m", "128M",
        "-netdev", "user,id=net0", "-device", "e1000,netdev=net0",
        "-smp", "4",
        "-audiodev", "dsound,id=snd0", "-device", "intel-hda",
        "-device", "hda-output,audiodev=snd0",
        "-drive", "if=pflash,format=raw,readonly=on,file=" + fw,
        "-drive", "format=raw,file=fat:rw:" + os.path.join(ROOT, "esp-liftoff"),
        "-serial", "file:" + SLOG,
        "-monitor", "tcp:127.0.0.1:%d,server=on,wait=off" % PORT,
        "-no-reboot", "-no-shutdown", "-display", "none"]
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

spawned = wait_log("spawned pid=1", 480)
print("spawned seen:", spawned)
time.sleep(5.0)
s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
time.sleep(1.0)
try:
    s.recv(65536)
except OSError:
    pass
s.sendall(b"info registers -a\n")
time.sleep(3.0)
s.settimeout(3.0)
out = b""
try:
    while True:
        c = s.recv(65536)
        if not c:
            break
        out += c
except socket.timeout:
    pass
p.kill()
open(os.path.join(ROOT, "_regs2.txt"), "w", encoding="utf-8").write(out.decode("utf-8", "replace"))
txt = out.decode("utf-8", "replace")
import re
for m in re.finditer(r"CPU#(\d+)[\s\S]*?RIP=([0-9a-f]{16})[\s\S]*?CR3=([0-9a-f]{16})", txt):
    print("CPU" + m.group(1), "RIP=" + m.group(2), "CR3=" + m.group(3))
