//! 负例夹具：故意让中立层依赖 UEFI 实现，用于验证 check_arch_isolation.py 真会失败。

use efi::types::Status;

pub fn bogus(_s: Status) {}
