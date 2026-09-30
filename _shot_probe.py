import os, socket, subprocess, sys, time

ROOT = r"F:\boruix-project"
q = None
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    if line.startswith("QEMU_DIR="):
        q = line.strip().split("=", 1)[1]
exe = os.path.join(q, "qemu-system-x86_64.exe")
fw = os.path.join(q, "share", "edk2-x86_64-code.fd")
PORT = 45483
qemu = [exe, "-m", "256", "-smp", "4", "-display", "none", "-no-reboot",
        "-monitor", "tcp:127.0.0.1:%d,server=on,wait=off" % PORT,
        "-drive", "format=raw,file=" + os.path.join(ROOT, "systemdisk.img"),
        "-drive", "if=pflash,format=raw,readonly=on,file=" + fw,
        "-drive", "format=raw,file=fat:rw:" + os.path.join(ROOT, "esp-liftoff")]
p = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
s = None
for _ in range(60):
    try:
        s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
        break
    except OSError:
        time.sleep(0.5)
if s is None:
    print("FAIL: no monitor")
    p.kill()
    sys.exit(1)
f = s.makefile("rwb")

def mon(cmd):
    f.write((cmd + "\n").encode())
    f.flush()

# 等 init spawned（用串口 file 辅助判定时机——它至少能到 spawn）
deadline = time.time() + 420
shot = 0
while time.time() < deadline:
    time.sleep(10)
    shot += 1
    mon("screendump F:\\boruix-project\\_shot%d.ppm" % shot)
    time.sleep(1.0)
    p = os.path.join(ROOT, "_shot%d.ppm" % shot)
    try:
        with open(p, "rb") as h:
            data = h.read()
        # PPM 是文本头 + RGB；找 "BORUIX" 之类不可靠，直接看大小变化即可
        print("shot%d bytes=%d" % (shot, len(data)))
    except OSError:
        print("shot%d missing" % shot)
    if shot >= 6:
        break
p.kill()
print("done")
