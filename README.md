# BORUIX tools — 系统工具（系统集成 / 构建 / 验收）

本目录是** Boruix 系统自身的开发与验收工具**：编译内核、打包镜像、用真实
QEMU 硬件链路做验收。它服务于**仓库主人 / 系统开发者**。

> **本目录不是第三方 SDK。** 面向第三方开发者的交叉编译产物（sysroot、
> `boruix-clang`、target 定义、cargo-config 模板）在仓库顶层 `sdk/` 目录
> （见该目录 README；内容由 SDK 计划阶段 1.1–1.3 产出）。

## 职责

- 内核编译与两遍符号生成（`tools_build/build.py` + `symbols.py`）
- Limine bootloader 集成（brxLimine fork 的 BIOS stage2 交叉编译）
- 可引导 ISO 打包、数据盘镜像创建（`mkimg`，EXT2）
- QEMU 启动与真实按键交互验收（`checks/` 下的验收 harness）
- 第三方程序构建通道（`b3p`：仓库内第三方程序清单 → diskfiles/3p/）

## 用法

    python main.py --help          # 全部子命令
    python main.py br              # 编译 + 打 ISO + QEMU 启动
    python main.py b3p             # 构建第三方程序（清单见 tools_build/b3p.py）
    python checks/regression/selftest.py   # 内核自检全量

## checks/ — 内核验收 harness

24 个验收脚本按域分类（boot / interactive / process / regression /
terminal / ievents）。它们只走真实链路：QEMU monitor `sendkey` 注入真实
PS/2 扫描码、串口日志判 PANIC——**不伪造证据（S39）**。这些脚本属于系统
验收工具，不属于第三方 SDK。

## 历史

2026-10 由 `sdk/` 改名而来：旧名字承诺了本目录从未提供的东西（第三方
开发工具），改名以正名分。真正的 SDK 从零建在新的 `sdk/` 里。
