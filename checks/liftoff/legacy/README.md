# 旧实现的检查（已归档）

- `l1_boot_check_old_impl.py`：面向 **旧实现** 的端到端验收，锚点是旧内核的串口输出
  （`[boot] liveCD mode` / `init: loaded`），**不适用于 gen2**。
- gen2 的检查在上一层：见 `../README.md`。
- 保留原因：回溯旧实现的验收方式与锚点选择。
