# SDK aarch64 相关（已归档）

> 状态：已归档。aarch64 支持已暂停，代码库只保留 x86-64。
> 这些文件保留供未来恢复 aarch64 支持时参考。

## 归档内容

- `firmware/QEMU_EFI.fd` — aarch64 AAVMF (EDK2) UEFI 固件，官方 `qemu-efi-aarch64` 包提取
- `extract_firmware.py` — 从 `.deb` 包提取 `QEMU_EFI.fd` 的脚本

## 来源

`QEMU_EFI.fd` 来自 Debian 官方包 `qemu-efi-aarch64_2026.05-2_all.deb`，
位于包内 `usr/share/AAVMF/QEMU_EFI.fd`。
