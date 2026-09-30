import os, socket, subprocess, sys, time

ROOT = r"F:\boruix-project"
q = None
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    if line.startswith("QEMU_DIR="):
        q = line.strip().split("=", 1)[1]
exe = os.path.join(q, "qemu-system-x86_64.exe")
fw = os.path.join(q, "share", "edk2-x86_64-code.fd")
PORT = 45601
qemu = [exe, "-m", "256", "-smp", "4", "-display", "none", "-no-reboot",
        "-serial", "tcp:127.0.0.1:%d,server=on,wait=off" % PORT,
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
    print("FAIL: no serial socket")
    p.kill()
    sys.exit(1)
s.settimeout(1.0)
log = open(os.path.join(ROOT, "_tcp_serial.log"), "wb")
data = b""
deadline = time.time() + 420
try:
    while time.time() < deadline:
        try:
            chunk = s.recv(65536)
            if not chunk:
                log.write(b"[connection closed by qemu]")
                break
            log.write(chunk)
            log.flush()
            data += chunk
        except socket.timeout:
            pass
        if b"username:" in data:
            break
finally:
    log.close()
    p.kill()
txt = data.decode("utf-8", "replace")
print("bytes=", len(data), "spawn=", "spawned pid=1" in txt, "username=", "username:" in txt, "shell=", "BORUIX shell" in txt)
after = txt.split("spawned pid=1", 1)[1] if "spawned pid=1" in txt else ""
print("---- after spawn ----")
print(after[-1500:])
