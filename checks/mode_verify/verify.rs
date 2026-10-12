// mode.rs 的**宿主验证器**（不是复制代码——用 include! 引入同一份源码）。
//
// 为什么需要：`cargo test -p libc` 跑不通，真障碍是 libc 用 `#[no_mangle]` 导出了
// 宿主 CRT 自己的符号（实测 LNK2005: atexit），**任何 crate 拆分都解决不了**。
// 本项目的既有做法（见 tools/checks/math_verify/verify.rs）是把**纯逻辑**留在可 include! 的
// 文件里，宿主侧引入**同一份源码**验证。`mode.rs` 正是这样的纯模块。
//
// 运行：rustc -O --edition 2021 verify.rs -o verify.exe && ./verify.exe

// `mode.rs` 里 `use crate::ctypes::mode_t;` —— 在验证器里 `crate` 是本程序，故这里补同一别名。
mod ctypes {
    pub type mode_t = u32;
}

// 用 `#[path]` 而不是 `include!`：`mode.rs` 以 `//!` 内部文档注释开头，而 `include!`
// 展开处不允许内部文档注释（E0753，实测）。`#[path]` 引入的是真正的模块文件，合法。
// （同族说明见 tools/checks/builtins_verify/verify.rs 顶部。）
#[path = "../../../libc/src/mode.rs"]
mod mode;

use mode::perms_from_mode;

static mut FAILS: u32 = 0;

fn ck(what: &str, ok: bool) {
    println!("{} {}", if ok { "ok  " } else { "FAIL" }, what);
    if !ok {
        unsafe { FAILS += 1 };
    }
}

fn main() {
    // 1. POSIX 语义：0644 = owner rw ⇒ (可读, 可写, 不可执行)
    ck("0644 → owner rw（可读可写不可执行）", perms_from_mode(0o644, 0) == (true, true, false));
    ck("0400 → 只读", perms_from_mode(0o400, 0) == (true, false, false));
    ck("0200 → 只写", perms_from_mode(0o200, 0) == (false, true, false));
    ck("0100 → 只执行", perms_from_mode(0o100, 0) == (false, false, true));
    ck("0755 → owner rwx", perms_from_mode(0o755, 0) == (true, true, true));
    ck("0000 → 无权限", perms_from_mode(0, 0) == (false, false, false));

    // 2. 组/其他的位**不影响**结果（本内核只表示 owner 三位——诚实边界，非近似）
    ck("0644 与 0600 同解（组/其他不可表示）",
       perms_from_mode(0o644, 0) == perms_from_mode(0o600, 0));
    ck("0755 与 0700 同解", perms_from_mode(0o755, 0) == perms_from_mode(0o700, 0));

    // 3. umask：先 mode & !umask，再取 owner 位
    ck("umask 0200 清 owner 写", perms_from_mode(0o644, 0o200) == (true, false, false));
    ck("umask 0400 清 owner 读", perms_from_mode(0o644, 0o400) == (false, true, false));
    ck("umask 0100 清 owner 执行", perms_from_mode(0o755, 0o100) == (true, true, false));
    ck("umask 0777 清空", perms_from_mode(0o755, 0o777) == (false, false, false));
    // 诚实边界：清组/其他的掩码**不可观测**（umask 022 对 0644 毫无影响）
    ck("umask 022 对 0644 无影响（组/其他不可表示）",
       perms_from_mode(0o644, 0o022) == perms_from_mode(0o644, 0));

    // 4. **回归锁**：改动前的「最低 3 位当 r/w/x」必须与现在**不同**——
    //    否则这次适配没有意义（0644 的旧解是「只读」，会丢失 owner 写位）。
    let legacy = ((0o644 & 0b100) != 0, (0o644 & 0b010) != 0, (0o644 & 0b001) != 0);
    ck("旧约定把 0644 解成只读（这正是要修的）", legacy == (true, false, false));
    ck("新解与旧解**必须不同**（回归锁）", legacy != perms_from_mode(0o644, 0));

    let f = unsafe { FAILS };
    println!("mode_verify: fails={}", f);
    std::process::exit(f as i32);
}