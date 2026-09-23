"""J-TOKEN-B 验收：console owner 真值的用户态端到端链路（真实 QEMU）。

## 本脚本钉死的语义（重要，勿按「owner == 自己 pid」写断言）

令牌属于 **console 对象**，不属于恰好持有 fd 的进程。fd 表是**继承**的
（`clone_inherited_fd_table`：init → shell → 前台子进程），故子进程拿到的
stdin/stdout/stderr 是**同一个** console 节点，owner 自然与父相同。

实测：以 alice 身份从 shell 跑 tokendemo 时，owner=1（init）而进程 pid≠1。
**这不是缺陷**——「谁该持令牌、何时移交」是用户态策略（J-TOKEN-C），
内核只如实报告当前 owner。本验收因此断言：

  1. 三条 fd 都能经公开 `fstat` 读到 owner（链路成立）；
  2. 三条 fd 的 owner **彼此一致**（同一个 console 对象 → 同一个 owner）；
  3. owner **非 0**（不是「无主」——init 已持有）；
  4. owner 是一个**真实存在的 pid**（与内核 started 行或进程表对得上）；
  5. 三条 fd 的 is_terminal 都为 1（J-TOKEN-A 真值未被本次改动破坏）。
"""
import os, re, socket, subprocess, sys, threading, time

ROOT = r"F:\boruix-project"
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable", "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
PORT = 45567
BOOT_WAIT = int(os.environ.get("BOOT_WAIT", "300"))

qemu = [QEMU, "-cdrom", os.path.join(ROOT, "boruix.iso"), "-hda", os.path.join(ROOT, "disk.img"),
        "-boot", "order=d", "-m", "256", "-display", "none", "-serial", "stdio",
        "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT, "-no-reboot"]
proc = subprocess.Popen(qemu, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
buf = bytearray()

def reader():
    while True:
        c = proc.stdout.read(1)
        if not c:
            return
        buf.extend(c)

threading.Thread(target=reader, daemon=True).start()

sock = None
for _ in range(120):
    try:
        sock = socket.create_connection(("127.0.0.1", PORT), timeout=2)
        break
    except OSError:
        time.sleep(0.5)
if sock is None:
    print("[jtokenb] cannot reach monitor"); proc.kill(); sys.exit(2)
mon = sock.makefile("rwb")

def key(name, d=0.35):
    mon.write(("sendkey " + name + chr(10)).encode()); mon.flush(); time.sleep(d)

KMAP = {" ": "spc", "/": "slash", "-": "minus", ".": "dot", "_": "shift-minus"}
def type_str(s, d=0.35):
    for ch in s:
        key(KMAP.get(ch, ch), d)

def snap():
    return bytes(buf).decode("utf-8", "replace")

def wait_for(needle, secs):
    dl = time.time() + secs
    while time.time() < dl:
        if needle in snap():
            return True
        time.sleep(1.0)
    return False

fails = []
def check(name, ok, why=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name + ("" if ok else "  (" + why + ")"))
    if not ok:
        fails.append(name)

print("[jtokenb] waiting up to %ds for login prompt ..." % BOOT_WAIT)
check("login_prompt_seen", wait_for("username:", BOOT_WAIT), "no login prompt")
type_str("alice"); key("ret", 1.5)
check("password_prompt_seen", wait_for("password:", 25), "no password prompt")
type_str("alicepw"); key("ret", 3.0)
check("shell_ready", wait_for("alice:/$", 40), "could not reach the shell")

print("[jtokenb] running /programs/tokendemo.elf ...")
type_str("/programs/tokendemo.elf"); key("ret", 6.0)
check("tokendemo_ran", wait_for("[tokendemo]", 30), "tokendemo produced no output")

text = snap()
check("tokendemo_pass", "[tokendemo] PASS" in text, "no PASS line")
check("no_fail_lines", "[tokendemo] FAIL" not in text, "FAIL line present")

m_pid = re.search(r"\[tokendemo\] my pid = (\d+)", text)
check("pid_printed", m_pid is not None, "no pid line")

rows = re.findall(r"\[tokendemo\] fd(\d) is_terminal=(\d) console_owner=(\d+)", text)
check("three_fd_rows", len(rows) >= 3, "expected 3 fd rows, got %d" % len(rows))

if rows:
    rows = rows[:3]
    owners = set(r[2] for r in rows)
    terms  = set(r[1] for r in rows)
    check("owners_all_agree", len(owners) == 1, "owners differ: %s" % sorted(owners))
    check("owner_not_unowned", owners != {"0"}, "owner is 0 (unowned) - nobody holds the console")
    check("all_terminals", terms == {"1"}, "is_terminal values: %s" % sorted(terms))

    owner = rows[0][2]
    # owner 必须是真实存在的 pid：与内核的同一次运行记录对拍。
    started = re.findall(r"boruix: started pid=(\d+)", text)
    check("owner_is_a_real_pid",
          owner in started or owner == "1",
          "owner=%s not among started pids %s" % (owner, started))

    if m_pid:
        print("[jtokenb] note: tokendemo pid=%s, console owner=%s (inherited from the console holder)" % (m_pid.group(1), owner))

print("[jtokenb] serial bytes: %d" % len(buf))
proc.kill()
print("[jtokenb] " + ("ALL PASS (%d checks)" % (0,) if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(0 if not fails else 1)