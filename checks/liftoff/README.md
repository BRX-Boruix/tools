# liftoff 检查（gen2）

三层验收（见 ADR-052），各自独立可跑：

| 层 | 脚本 | 作用 |
|---|---|---|
| **PRE-1** | `asm_check.py` | 离线反汇编核对：最新的 UEFI `.efi` 里必须出现特定指令（`hlt`/`outb`/`inb`）；`cli`/`sti` 作为备注 |
| **PRE-2** | `l3_gen2_entry_check.py` | QEMU/OVMF 端到端：串口日志出现 `[liftoff] gen2 up` |
| **PRE-3** | `../regression/check_arch_isolation.py` | 静态隔离：抽象层不得出现实现层依赖 |

运行（在 `tools` 目录下）：

```
python checks/liftoff/asm_check.py
python checks/liftoff/l3_gen2_entry_check.py
python checks/regression/check_arch_isolation.py
```

注意：`l2_frozen_regs_check.py` 属于早期尝试，**未纳入三层验收**；
面向旧实现的检查已归档到 `legacy/`。
