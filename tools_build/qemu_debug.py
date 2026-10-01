"""QEMU 诊断客户端：HMP 监视器、GDB 远程串行协议（RSP）、帧缓冲截屏。

为什么需要它们（而不是「看串口日志就够了」）：

* **RSP（`-s`）**：内核在入口就跑飞时串口一个字都没有。用 RSP 在内核入口下硬件断点、
  逐条 `stepi`，才看清 `RSP` 是在第 5 条指令被**显式**置零的（哨兵实验：把 `xor ebp,ebp`
  换成 `mov ebp,0xdeadbeef`，`RSP` 仍是 0，所以不是读 `[RBP]`）。这条证据直接指向
  「内核从全局读自己的栈指针，而那个全局需要 ELF 重定位」。
* **HMP（`-monitor`）**：内核不崩也不输出时，`info registers` 一次就能区分「紧循环」与
  「`hlt` 等中断」——`HLT=0` 且 `RFL` 的 `IF=0` 说明它在自旋，而不是在等中断。
* **`screendump`**：内核的 panic 消息可能只进帧缓冲控制台（串口按字节检查过确实没有），
  截屏是唯一的取证途径。

平台：`kill_existing()` 用 Windows 的 `taskkill`（QEMU 在 Windows 上不随父进程退出）。
非 Windows 平台需在此补一份实现——**不静默假装成功**，见 `kill_existing` 的分支。
"""

import os
import socket
import struct
import subprocess
import sys
import time
import zlib

# RSP 默认端口（`-s` 等价于 `-gdb tcp::1234`）。
DEFAULT_GDB_PORT = 1234
# RSP 单包上限：`g` 的寄存器块约 400 字节，留足余量。
RSP_MAX_PACKET = 1 << 20
# x86_64 上 `g` 返回 24 个 8 字节寄存器，顺序固定（RAX, RBX, RCX, RDX, RSI, RDI,
# RBP, RSP, R8..R15, RIP, EFLAGS, CS, SS, DS, ES, FS, GS）。
X86_64_REGISTER_COUNT = 24
REG_RAX, REG_RBX, REG_RCX, REG_RDX = 0, 1, 2, 3
REG_RSI, REG_RDI, REG_RBP, REG_RSP = 4, 5, 6, 7
REG_RIP = 16
REG_EFLAGS = 17


class QemuDebugError(Exception):
    """与 QEMU 的调试通道交互失败。"""


def kill_existing(timeout_s: float = 5.0) -> None:
    """杀掉残留的 QEMU。

    Windows 上 QEMU 不随父进程退出，且会**持有** `fat:rw:` 的 ESP 目录——残留一个进程，
    下一次运行就会因为目录被占用而失败（实测过多次）。非 Windows 平台请补实现。
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/IM", "qemu-system-x86_64.exe"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        time.sleep(timeout_s)
        return
    raise QemuDebugError(
        "kill_existing 未在平台 %r 上实现（不静默跳过：残留 QEMU 会占住 ESP 目录）"
        % sys.platform
    )


def rsp_checksum(payload: bytes) -> bytes:
    """RSP 包尾校验和：所有字节和取低 8 位，两位十六进制。"""
    return b"%02x" % (sum(payload) & 0xFF)


class RspClient:
    """GDB 远程串行协议的最小客户端（只实现诊断需要的命令）。"""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_GDB_PORT, timeout: float = 20.0):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)

    def close(self) -> None:
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def _send(self, body: str) -> None:
        payload = body.encode("ascii")
        self._sock.sendall(b"$" + payload + b"#" + rsp_checksum(payload))

    def _recv_packet(self, timeout: float = None):
        """收到一个 `$...#xx` 包并回 `+`；超时返回 `None`。"""
        if timeout is not None:
            self._sock.settimeout(timeout)
        buf = b""
        while True:
            try:
                chunk = self._sock.recv(1)
            except socket.timeout:
                return None
            if not chunk:
                raise QemuDebugError("RSP 连接在收到完整包之前关闭")
            if chunk in (b"+", b"-"):
                continue
            if chunk != b"$":
                continue
            body = b""
            while True:
                ch = self._sock.recv(1)
                if not ch:
                    raise QemuDebugError("RSP 包未以 # 结束就断流")
                if ch == b"#":
                    self._sock.recv(2)  # 校验和，QEMU 不校验，这里也不假装校验
                    self._sock.sendall(b"+")
                    return body
                body += ch
                if len(body) > RSP_MAX_PACKET:
                    raise QemuDebugError("RSP 包超过 %d 字节" % RSP_MAX_PACKET)

    def command(self, body: str, timeout: float = 20.0) -> bytes:
        self._send(body)
        packet = self._recv_packet(timeout=timeout)
        if packet is None:
            raise QemuDebugError("命令 %r 超时未收到应答" % body)
        return packet

    def registers(self, timeout: float = 20.0) -> list:
        """`g`：返回 24 个 64 位寄存器（顺序见模块常量）。"""
        raw = bytes.fromhex(self.command("g", timeout=timeout).decode("ascii"))
        count = len(raw) // 8
        if count < X86_64_REGISTER_COUNT:
            raise QemuDebugError("`g` 只返回了 %d 个寄存器，期望 %d" % (count, X86_64_REGISTER_COUNT))
        return [int.from_bytes(raw[i * 8:(i + 1) * 8], "little") for i in range(count)]

    def set_breakpoint(self, address: int, kind: int = 4) -> bool:
        """`Z0,addr,kind`：软件断点。`kind` 为指令长度（x86 用 4 表示任意）。"""
        reply = self.command("Z0,%x,%d" % (address, kind))
        return reply == b"OK"

    def continue_(self, timeout: float = None):
        """`c`：继续执行；返回停机原因包（`T..` / `S..`），超时返回 `None`。"""
        self._send("c")
        return self._recv_packet(timeout=timeout)

    def step(self, timeout: float = 20.0):
        """`s`：单步一条指令。"""
        self._send("s")
        return self._recv_packet(timeout=timeout)

    def read_memory(self, address: int, length: int) -> bytes:
        """`m addr,len`：读内存。返回真实字节，长度不符即报错。"""
        reply = self.command("m%x,%x" % (address, length))
        if reply.startswith(b"E"):
            raise QemuDebugError("读内存 %#x/%d 被拒: %s" % (address, length, reply.decode("ascii", "replace")))
        data = bytes.fromhex(reply.decode("ascii"))
        if len(data) != length:
            raise QemuDebugError("读内存 %#x 期望 %d 字节，实得 %d" % (address, length, len(data)))
        return data

    def read_cstring(self, address: int, limit: int = 512) -> str:
        """读一个 NUL 结尾字符串（用于把 panic 消息从内存里取出来）。"""
        out = bytearray()
        cursor = address
        while len(out) < limit:
            chunk = self.read_memory(cursor, 16)
            for byte in chunk:
                if byte == 0:
                    return out.decode("utf-8", errors="replace")
                out.append(byte)
            cursor += 16
        raise QemuDebugError("字符串在 %d 字节内没有结尾 NUL" % limit)


class MonitorClient:
    """QEMU HMP 监视器客户端（`-monitor tcp:host:port,server,nowait`）。"""

    PROMPT = b"(qemu)"

    def __init__(self, host: str = "127.0.0.1", port: int = 45454, timeout: float = 10.0):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._drain(timeout)

    def _drain(self, timeout: float) -> bytes:
        self._sock.settimeout(timeout)
        buf = b""
        try:
            while True:
                chunk = self._sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if self.PROMPT in buf:
                    break
        except socket.timeout:
            pass
        return buf

    def command(self, text: str, wait_s: float = 1.5) -> str:
        """执行一条 HMP 命令，返回其输出文本（显式 UTF-8，替换非法序列）。"""
        self._sock.sendall((text + "\n").encode("ascii"))
        time.sleep(wait_s)
        return self._drain(wait_s).decode("utf-8", errors="replace")

    def close(self) -> None:
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


def ppm_to_png(ppm: bytes) -> bytes:
    """把 QEMU `screendump` 产出的二进制 PPM（P6）转成 PNG。

    自己转而不是依赖 Pillow：诊断链路不该为一个格式转换引入外部依赖（S35）。
    """
    if not ppm.startswith(b"P6"):
        raise QemuDebugError("不是 P6 PPM（screendump 默认产出 P6）")
    fields = []
    index = 2
    while len(fields) < 3:
        while index < len(ppm) and ppm[index:index + 1].isspace():
            index += 1
        if ppm[index:index + 1] == b"#":
            while index < len(ppm) and ppm[index:index + 1] != b"\n":
                index += 1
            continue
        start = index
        while index < len(ppm) and not ppm[index:index + 1].isspace():
            index += 1
        fields.append(int(ppm[start:index]))
    index += 1  # 跳掉分隔空白
    width, height, maxval = fields
    if maxval != 255:
        raise QemuDebugError("只支持 8 位 PPM（maxval=%d）" % maxval)
    expected = width * height * 3
    pixels = ppm[index:index + expected]
    if len(pixels) != expected:
        raise QemuDebugError("PPM 像素数据不足: 期望 %d，实得 %d" % (expected, len(pixels)))
    raw = b"".join(b"\x00" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def wait_for_serial(log_path: str, marker: bytes, deadline_s: float, poll_s: float = 2.0,
                    process=None) -> bool:
    """轮询串口日志直到出现 `marker`；QEMU 提前退出则立即返回 False。"""
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        if os.path.isfile(log_path):
            with open(log_path, "rb") as fh:
                if marker in fh.read():
                    return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(poll_s)
    return False


def wait_for_serial_quiet(log_path: str, deadline_s: float, quiet_s: float = 25.0,
                          poll_s: float = 5.0, process=None):
    """等串口日志停止增长（内核停机或进入空闲），返回读到的原始字节。"""
    deadline = time.monotonic() + deadline_s
    last = -1
    stable = 0.0
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        size = os.path.getsize(log_path) if os.path.isfile(log_path) else 0
        if size > 0 and size == last:
            stable += poll_s
            if stable >= quiet_s:
                break
        else:
            stable = 0.0
        last = size
        if process is not None and process.poll() is not None:
            break
    if not os.path.isfile(log_path):
        return b""
    with open(log_path, "rb") as fh:
        return fh.read()
