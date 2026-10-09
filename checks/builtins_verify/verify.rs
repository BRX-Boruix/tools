// libsys 的 builtins（memcpy/memmove/memset/memcmp）的**宿主对照测试**。
// 为什么要有它：这四个函数是整个用户态的 C ABI 内存原语，一旦改错，全系统都会坏——
// 而"在 QEMU 里跑一遍"要 8 分钟且只能给出"某个程序挂了"这种弱信号。
// 这里把它们与**逐字节参考实现**在大量长度/对齐/重叠组合上逐字节比对。
// 用 #[path] 而不是 include!：被引入的文件以 `//!` 内部文档注释开头，
// 而 include! 展开处不允许内部文档注释（E0753）。#[path] 是真正的模块文件，合法。
#[path = "../../../libsys/src/builtins.rs"]
mod builtins;
use core::ffi::c_void;

fn ref_memcpy(d: &mut [u8], s: &[u8]) { for i in 0..s.len() { d[i] = s[i]; } }
fn ref_memmove(d: &mut [u8], s: &[u8], n: usize) {
    // 参考：先拷到临时缓冲（语义最清楚）
    let tmp: Vec<u8> = (0..n).map(|i| s[i]).collect();
    for i in 0..n { d[i] = tmp[i]; }
}

fn main() {
    let mut fails = 0u32;
    // ---- memcpy：长度 0..=160，src/dst 各 4 种相对对齐 ----
    for n in 0..=160usize {
        for sa in 0..4usize {
            for da in 0..4usize {
                let mut src = vec![0u8; n + 8];
                let mut dst = vec![0u8; n + 8];
                for i in 0..src.len() { src[i] = (i * 7 + 3) as u8; }
                let mut want = vec![0u8; n + 8];
                for i in 0..dst.len() { want[i] = 0xA5; }
                for i in 0..dst.len() { dst[i] = 0xA5; }
                unsafe {
                    builtins::memcpy(dst[da..].as_mut_ptr() as *mut c_void,
                                     src[sa..].as_ptr() as *const c_void, n);
                }
                ref_memcpy(&mut want[da..da + n], &src[sa..sa + n]);
                if dst != want { println!("memcpy FAIL n={n} sa={sa} da={da}"); fails += 1; }
            }
        }
    }
    // ---- memset：长度 0..=160，偏移 0..3 ----
    for n in 0..=160usize {
        for da in 0..4usize {
            for &c in &[0u8, 0xDD, 0xFF, 0x5A] {
                let mut dst = vec![0x11u8; n + 8];
                let mut want = vec![0x11u8; n + 8];
                unsafe { builtins::memset(dst[da..].as_mut_ptr() as *mut c_void, c as i32, n); }
                for i in 0..n { want[da + i] = c; }
                if dst != want { println!("memset FAIL n={n} da={da} c={c:#x}"); fails += 1; }
            }
        }
    }
    // ---- memmove：**含重叠**（dst 在 src 之前/之后，偏移 -40..=40）----
    for n in 0..=96usize {
        for off in -40i32..=40 {
            let total = n + 80;
            let base: Vec<u8> = (0..total).map(|i| (i * 13 + 5) as u8).collect();
            // src 起点固定 40；dst 起点 = 40 + off（需落在缓冲内）
            let s = 40usize;
            let d = (40i32 + off) as usize;
            if d + n > total || s + n > total { continue; }
            let mut buf = base.clone();
            let mut want = base.clone();
            unsafe {
                builtins::memmove(buf[d..].as_mut_ptr() as *mut c_void,
                                  buf[s..].as_ptr() as *const c_void, n);
            }
            ref_memmove(&mut want[d..], &base[s..], n);
            if buf != want { println!("memmove FAIL n={n} off={off}"); fails += 1; }
        }
    }
    // ---- memcmp ----
    for n in 0..=64usize {
        let a: Vec<u8> = (0..n).map(|i| i as u8).collect();
        let mut b = a.clone();
        unsafe {
            if builtins::memcmp(a.as_ptr() as *const c_void, b.as_ptr() as *const c_void, n) != 0 {
                println!("memcmp FAIL equal n={n}"); fails += 1;
            }
        }
        if n > 0 {
            b[n - 1] = b[n - 1].wrapping_add(1);
            unsafe {
                if builtins::memcmp(a.as_ptr() as *const c_void, b.as_ptr() as *const c_void, n) == 0 {
                    println!("memcmp FAIL diff n={n}"); fails += 1;
                }
            }
        }
    }
    println!("builtins 宿主对照：fails={fails}");
}
