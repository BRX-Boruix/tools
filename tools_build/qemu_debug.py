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
import threading
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

    def __init__(self, sock):
        """接一个**已连接**的 socket。

        真机走 `RspClient.connect()`；测试用 `socket.socketpair()` 注入——
        这样测试走的是与真机完全相同的收发代码路径，不需要 mock。
        """
        self._sock = sock
        # 诊断钩子：设为可调用对象就打印原始收发帧。排查协议问题用，默认关。
        self.trace = None

    @classmethod
    def connect(cls, host: str = "127.0.0.1", port: int = DEFAULT_GDB_PORT,
                timeout: float = 20.0):
        """连到 QEMU 的 gdbstub（`-s` 等价于 `-gdb tcp::1234`）。"""
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(timeout)
        return cls(sock)

    def close(self) -> None:
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def _send(self, body: str) -> None:
        payload = body.encode("ascii")
        frame = b"$" + payload + b"#" + rsp_checksum(payload)
        if self.trace:
            self.trace("%7.2fs >> %s" % (time.monotonic() % 1000, frame.decode("ascii", "replace")))
        self._sock.sendall(frame)

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
                    if self.trace:
                        self.trace("%7.2fs << %s" % (time.monotonic() % 1000, body.decode("ascii", "replace")))
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

    def continue_(self) -> None:
        """`c`：让 VM 继续执行。**不读应答**。

        停机包要等断点命中（可能几分钟后）才来，读它属于 `wait_for_stop` 的职责。
        在这里顺手读一次应答，会把停机包**读走又丢掉**——调用方再等就什么都没有了。
        """
        self._send("c")

    def wait_for_stop(self, timeout_s: float):
        """等一个停机包（`T..` / `S..`），返回它；超时返回 `None`。

        内核运行期间 gdbstub 会插入非停机包（`O` 控制台输出等），必须跳过；
        每轮只等一小段，这样超时是**确定的**而不是被一个长阻塞吞掉。
        """
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            packet = self._recv_packet(timeout=min(remaining, 5.0))
            if packet is None:
                continue
            if packet[:1] in (b"T", b"S"):
                return packet

    def step(self, timeout: float = 20.0):
        """`s`：单步一条指令，返回停机包（可能带非停机包前缀，调用方自行判断）。"""
        self._send("s")
        # 与 `continue_` 同理：应答可能先来一个非停机包（`O`），不能只读一次。
        return self.wait_for_stop(timeout)

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


class SerialBuffer:
    """串口字节流累积器。

    **为什么不能对每块单独查标记**：串口数据按块到达，一个标记极可能被切成两块
    （`...userna` + `me:...`）。朴素实现「每块各自 find」会漏掉它，于是检查偶发
    超时——这种失败最难查，因为它取决于分块时机。
    """

    __slots__ = ("_data",)

    def __init__(self):
        self._data = bytearray()

    def feed(self, chunk: bytes) -> None:
        self._data.extend(chunk)

    def contains(self, marker: bytes) -> bool:
        return marker in self._data

    def text(self) -> str:
        # 串口输出是 UTF-8；边界处的半个字符用替换字符表示，不抛异常（S02）。
        return bytes(self._data).decode("utf-8", errors="replace")

    def line_count(self) -> int:
        # 直接数换行字节：解码后再数会被多字节字符与替换字符干扰。
        return self._data.count(0x0A)

    def __len__(self) -> int:
        return len(self._data)


class SerialCapture:
    """用 `-serial stdio` 启动 QEMU 并**实时**收集串口输出。

    为什么不用 `-serial file:`：QEMU 的 file 后端不在每次写入时刷新（仓库里
    `checks/interactive/l3_interactive.py` 记录了实测：静止 16 秒文件大小不变），
    落盘时机取决于内部缓冲——属未定义行为。依赖它的检查会随输出量大小而时灵时不灵：
    输出多到填满缓冲就「恰好能用」，输出少就永远读不到。`stdio` 由本进程实时读走，
    时序确定。

    调用方给出完整命令行；本类只管进程生命周期与字节流。
    """

    def __init__(self, command):
        self._process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._buffer = SerialBuffer()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    @property
    def buffer(self) -> SerialBuffer:
        return self._buffer

    @property
    def process(self):
        return self._process

    def _reader(self) -> None:
        try:
            while not self._stop.is_set():
                # **必须用 `read1` 而不是 `read`。** 管道上的 `read(n)` 会阻塞到
                # **读满 n 字节**（或 EOF）才返回，于是缓冲只按 n 的整数倍前进：
                # 末尾不满一块的标记要等到下一块填满才可见，输出一慢就拖到超时。
                # 实测代价：一次 `-serial stdio` 的 L5 检查因此 600 秒超时，而
                # 标记其实早在最终缓冲里（15338 字节）。`read1` 有数据就返回。
                chunk = self._process.stdout.read1(4096)
                if not chunk:
                    return
                self._buffer.feed(chunk)
        except (ValueError, OSError):
            # 收尾时关闭管道会让阻塞中的 read 抛错；这是正常收尾路径，不是失败。
            return

    def wait_for(self, marker: bytes, timeout_s: float, poll_s: float = 0.5) -> bool:
        """等 `marker` 出现；超时返回 False，**不假装成功**。"""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._buffer.contains(marker):
                return True
            if self._process.poll() is not None:
                # QEMU 已退出：给它一点时间交出剩余输出，再定论。
                self._thread.join(timeout=3.0)
                return self._buffer.contains(marker)
            time.sleep(poll_s)
        return self._buffer.contains(marker)

    def wait_quiet(self, timeout_s: float, quiet_s: float = 20.0,
                   poll_s: float = 1.0) -> None:
        """等到连续 `quiet_s` 秒没有新输出（内核停机或进入空闲）。"""
        deadline = time.monotonic() + timeout_s
        last = len(self._buffer)
        stable = 0.0
        while time.monotonic() < deadline:
            time.sleep(poll_s)
            size = len(self._buffer)
            if size == last:
                stable += poll_s
                if stable >= quiet_s:
                    return
            else:
                stable = 0.0
            last = size
            if self._process.poll() is not None:
                return

    def close(self) -> None:
        """停掉 QEMU 与读线程。用 taskkill：Windows 上 QEMU 不随父进程退出。"""
        self._stop.set()
        kill_existing(timeout_s=2.0)
        self._thread.join(timeout=5.0)
        if self._process.stdout is not None:
            try:
                self._process.stdout.close()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False
