# liftoff 检查（gen2）

三层验收（见 ADR-052），各自独立可跑。**目前没有统一 runner**：每个脚本自带
main() 与退出码，单独调用。是否要一个聚合入口（main.py check 之类）
**待所有者裁定**（A4 结论，见 docs/TODO/liftoff.md）。

| 层 | 脚本 | 作用 |
|---|---|---|
| **PRE-1** | `asm_check.py` | 离线反汇编核对：UEFI `.efi` 里必须出现特定指令与指令序列 |
| **PRE-2** | `l3_gen2_entry_check.py` | QEMU/OVMF 端到端（引导器层）：串口出现 `[liftoff] gen2 up` |
| **PRE-2** | `l5_handoff_check.py` | QEMU/OVMF 端到端（**交接层**）：串口出现 `username:`；`--matrix` 跑 §4.3 四格覆盖矩阵 |
| **PRE-2** | `diag_clients_check.py` | 诊断客户端真机验证：RSP 断点/单步/读内存、HMP 寄存器、`screendump` |
| **PRE-3** | `../regression/check_arch_isolation.py` | 静态隔离：抽象层不得出现实现层依赖；并强制 workspace 成员显式归类 |
| **PRE-3** | `../regression/check_catalog.py` | 本目录清册：每个脚本都必须被 README 登记（防止「存在却无人知道」） |
| **PRE-3** | `mock_impl_check.py` | 确认无人启用的 `impl-mock` 仍能编译（防止静默腐烂） |
| **PRE-3** | `../regression/config_paths_selftest.py` | **S01**：路径必须派生而非写死；含「换 cwd 结果不变」的行为性断言 |
| **PRE-3** | `../regression/run_smp_selftest.py` | `--smp`/`--no-smp` → QEMU 参数（**E1/S8 判据的输入**） |
| **PRE-3** | `../regression/symbols_selftest.py` | 地址→符号解析离线自检（真机失败诊断的入口，错了会指向错误函数） |
| **PRE-3** | `../regression/elf_image_selftest.py` | ELF64 解析器离线自检（合成 ELF 走公开 API；含**惰性校验**的访问期越界） |
| **PRE-3** | `../regression/iso9660_selftest.py` | ISO9660 解析器离线自检（合成 ISO 走公开 API；坏数据必须报错而非返回伪数据） |
| **PRE-3** | `../regression/diag_selftest.py` | 诊断模块离线自检（RSP 校验和、PPM→PNG、畸形输入拒绝、SerialBuffer 边界、停机包等待） |

运行（在 `tools` 目录下）：

```
python checks/liftoff/asm_check.py
python checks/liftoff/l3_gen2_entry_check.py
python checks/liftoff/l5_handoff_check.py             # 单格（约 4 分钟）
python checks/liftoff/l5_handoff_check.py --matrix    # §4.3 四格覆盖矩阵（约 20 分钟）
python checks/liftoff/l5_handoff_check.py --smp 4 --expect-cpus 4   # **S8 判据**：4 核必须报 4
python checks/liftoff/l5_handoff_check.py --matrix --expect-cpus auto   # **S8 矩阵**：每格期望自己的 --smp
python checks/liftoff/diag_clients_check.py
python checks/regression/check_arch_isolation.py
python checks/regression/check_catalog.py
python checks/regression/iso9660_selftest.py
python checks/regression/elf_image_selftest.py
python checks/regression/symbols_selftest.py
python checks/regression/run_smp_selftest.py
python checks/regression/config_paths_selftest.py
python checks/liftoff/mock_impl_check.py
python checks/regression/diag_selftest.py
```

注意：`l2_frozen_regs_check.py` 属于早期尝试，**未纳入三层验收**；
面向旧实现的检查已归档到 `legacy/`。
