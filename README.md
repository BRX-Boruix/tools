# BORUIX SDK

构建系统与工具链配置，用于编译内核与用户态程序。

## 职责
- 交叉编译 target 定义（`*.json` / 构建配置）
- 链接脚本（kernel 与用户程序的 linker script）
- 构建脚本与 Makefile/cargo 配置
- Limine bootloader 集成与镜像打包
- 内核/用户态程序的统一构建入口

## 内容规划
- `targets/`        — 各架构编译目标定义
- `linker/`         — 链接脚本
- `scripts/`        — 构建与打包脚本
- `boot/`           — Limine 配置与镜像素材
