# tools

**简体中文** | [English](#english)

**系统工具**——编译 BORUIX、打包成可引导镜像、在真实虚拟机里跑起来并做验收。

```bash
python main.py build      # 编译内核，生成可引导 ISO
python main.py run        # 用 QEMU 启动它
python main.py br         # 编译 + 启动，一步到位
```

---

## 这是什么

一个操作系统项目要能被开发，光有源码不够——还需要一整套**把源码变成可运行系统**的工具链：
编译、打包引导镜像、启动虚拟机、验证结果。这个仓库就是这套工具。

它服务的是**系统开发者**：改完内核，一条命令就能看到结果。

> **这不是给第三方开发者的 SDK。** 面向第三方的交叉编译产物（系统根目录、编译器包装、目标
> 定义）是另一回事，规划在仓库顶层的 `sdk/` 目录，**目前尚未落地**。

## 能做什么

| 子命令 | 作用 |
| --- | --- |
| `build` | 编译内核，生成可引导 ISO |
| `run` | 用 QEMU 启动 ISO |
| `br` | `build` + `run`，最常用 |
| `mkimg` | 创建数据盘镜像 |
| `limine-build` | 交叉编译引导程序 |
| `b3p` | 构建第三方程序 |

`run` 支持指定内存大小（默认 128M）与串口输出到终端。

开发时的默认流程就是 `br`：改代码、跑一条命令、直接看到系统启动。

## 引导镜像怎么来的

生成的 ISO 由两部分组成：

| 部分 | 内容 |
| --- | --- |
| **内核** | 编译产物，经两遍符号生成（第二遍用第一遍的符号表） |
| **引导程序** | 系统使用的引导程序分支，其早期阶段由专门的交叉编译器构建 |

内核编译需要两遍的原因是**自举式的**：某些数据结构的布局依赖符号地址，而这些地址要到第一次
链接之后才确定。所以先链接一次拿到符号表，再带着它编译一次。

## 数据盘

`mkimg` 创建 EXT2 格式的数据盘镜像，用于存放用户程序与测试数据。可以指定卷标。

镜像不是一个空盘：`diskfiles/` 目录下的内容会被放进去——包括若干测试音频文件、示例程序、
以及一个更深层的目录结构（用来验证目录遍历的正确性）。

> `diskfiles/` 中体积最大的一个音频文件不入库（体积原因），需要时自行准备。

## 验收工具

`checks/` 下是按域分类的**验收脚本**（23 个）：

| 分类 | 验证方向 |
| --- | --- |
| `boot` | 开机序列、系统盘安装、终端创建、打字风暴 |
| `interactive` | 真实按键交互的逐层验证 |
| `terminal` | 终端挂载、焦点、轮转、并行实例 |
| `process` | 进程批量启动、控制台服务、看门狗 |
| `ievents` | 输入事件链路（组件、等价性、第二阶段） |
| `regression` | 回归检查（自检全量、中断响应、调度器、指令集） |

**它们只走真实链路。** 这一点是这个仓库的核心纪律：

- 键盘输入通过虚拟机的监控接口注入**真实的 PS/2 扫描码**，而不是直接调用内部函数
- 判定系统崩溃靠**串口日志**里的实际输出，而不是查询内部状态

换句话说，验收脚本**不伪造证据**。一个"通过"必须意味着真实硬件链路上确实成功了。

这条纪律听起来是常识，但在系统开发里非常容易被破坏：当调试一个棘手问题时，直接读内部变量
比走完整链路快得多——可一旦这么做，验收就测不到真正的链路了。

## 第三方程序构建

系统支持运行第三方程序。`b3p` 负责把仓库内登记的第三方程序构建好并放进数据盘。

目前清单里有一个经典的示例程序，用来验证"外部编写的程序能否在这个系统上正常运行"。

## 历史

这个目录原名 `sdk/`，2026-10 改名为 `tools/`。

改名的原因是**正名分**：旧名字承诺了它从未提供的东西——第三方开发工具。它一直做的都是系统自身
的构建与验收。真正的 SDK 会从零建立在新的 `sdk/` 里。

## 构建

需要 Python 3 与 QEMU。运行 `python main.py --help` 查看全部子命令。

## 文件结构

```
tools/
├── main.py           # 命令入口
├── tools_build/      # 构建与打包实现
├── checks/           # 验收脚本（按域分类）
├── diskfiles/        # 放进数据盘的内容
└── limine.conf       # 引导程序配置
```

## 相关项目

- [`init`](https://github.com/BRX-Boruix/init) —— 系统初始化进程
- [`selftest`](https://github.com/BRX-Boruix/selftest) —— 系统自检程序
- [`brxLimine`](https://github.com/BRX-Boruix/brxLimine) —— 引导程序分支

## 许可

MIT License，版权归 Yang Borui 所有。详见 [LICENSE](LICENSE)。

---

# English

[简体中文](#tools) | **English**

**System tools** — build BORUIX, package it into a bootable image, run it in a real VM, and verify it.

```bash
python main.py build      # compile the kernel, produce a bootable ISO
python main.py run        # start it under QEMU
python main.py br         # build and run in one step
```

---

## What this is

An operating system project cannot be developed on source code alone — it needs a whole toolchain
that **turns that source into a running system**: compiling, packaging a bootable image, starting a
VM, and verifying the result. This repository is that toolchain.

It serves **system developers**: change the kernel, run one command, see the result.

> **This is not a third-party SDK.** Cross-compilation artifacts for third parties (a sysroot, a
> compiler wrapper, target definitions) are a separate matter, planned for the top-level `sdk/`
> directory, and **not yet in place**.

## What it does

| Subcommand | Purpose |
| --- | --- |
| `build` | Compile the kernel and produce a bootable ISO |
| `run` | Start the ISO under QEMU |
| `br` | `build` + `run`, the common case |
| `mkimg` | Create the data disk image |
| `limine-build` | Cross-compile the bootloader |
| `b3p` | Build third-party programs |

`run` accepts a memory size (128M by default) and can send serial output to the terminal.

The everyday loop is `br`: edit, run one command, watch the system boot.

## How the bootable image is produced

The resulting ISO has two parts:

| Part | Contents |
| --- | --- |
| **Kernel** | The compiled artifact, produced through two symbol passes (the second using the first's symbol table) |
| **Bootloader** | The project's bootloader fork, whose early stage is built with a dedicated cross-compiler |

The kernel needs two passes because the process is **self-referential**: the layout of certain data
structures depends on symbol addresses, and those are only settled after the first link. So it links
once to obtain the symbol table, then compiles again with it.

## The data disk

`mkimg` creates an EXT2 data disk image holding user programs and test data. A volume label can be
set.

The image is not empty: the contents of `diskfiles/` go into it — several test audio files, a sample
program, and a deeper directory structure (used to verify directory traversal).

> The largest audio file under `diskfiles/` is not committed (a matter of size); fetch or generate
> your own if needed.

## Acceptance tooling

`checks/` holds **acceptance scripts** organised by domain (23 of them):

| Domain | What it verifies |
| --- | --- |
| `boot` | The boot sequence, system disk install, terminal creation, typing storms |
| `interactive` | Layer-by-layer verification with real keystrokes |
| `terminal` | Terminal mounting, focus, rotation, parallel instances |
| `process` | Batch process startup, the console service, the watchdog |
| `ievents` | The input event chain (component, equivalence, second phase) |
| `regression` | Regression checks (full self-test, interrupt response, scheduler, instruction set) |

**They only take real paths.** That is this repository's central discipline:

- Keyboard input is injected through the VM monitor as **real PS/2 scancodes**, not by calling internal functions
- Crash detection reads **actual serial output**, not an internal state query

In other words the acceptance scripts **do not fabricate evidence**. A "pass" must mean the real
hardware path genuinely worked.

The rule sounds like common sense, but in systems work it is easily broken: while debugging a
stubborn problem, reading an internal variable is far quicker than driving the whole chain — and once
you do, the acceptance test no longer exercises the real path.

## Building third-party programs

The system runs third-party programs. `b3p` builds those registered in the repository and places them
on the data disk.

The list currently contains one classic sample program, used to verify that "an externally written
program can run on this system".

## History

The directory was originally named `sdk/` and was renamed `tools/` in 2026-10.

The reason was **to call it what it is**: the old name promised something it never provided —
third-party development tools. It had always been the system's own build and acceptance tooling. A
real SDK will be built from scratch under the new `sdk/`.

## Building

Requires Python 3 and QEMU. Run `python main.py --help` for all subcommands.

## Layout

```
tools/
├── main.py           # the command entry point
├── tools_build/      # build and packaging implementation
├── checks/           # acceptance scripts, organised by domain
├── diskfiles/        # contents placed on the data disk
└── limine.conf       # bootloader configuration
```

## Related projects

- [`init`](https://github.com/BRX-Boruix/init) — the system init process
- [`selftest`](https://github.com/BRX-Boruix/selftest) — the system self-test program
- [`brxLimine`](https://github.com/BRX-Boruix/brxLimine) — the bootloader fork

## License

MIT License, copyright Yang Borui. See [LICENSE](LICENSE).
