// qsort_core 的**退化输入**性能探针：大量相等键会不会退化成 O(n^2)？
// 动机：系统内 tcc 的链接一步 176 秒，而它用 qsort 排符号表；ELF 的局部符号名字为空
// ⇒ 存在大量"相等键"。宿主上秒级即可判定。
use core::ffi::{c_int, c_void};
#[path = "../../../libc/src/qsort_core.rs"]
mod qsort_core;
use qsort_core::core_qsort;
use std::time::Instant;

unsafe extern "C" fn cmp_key(a: *const c_void, b: *const c_void) -> c_int {
    unsafe {
        let x = *(a as *const u32);
        let y = *(b as *const u32);
        if x < y { -1 } else if x > y { 1 } else { 0 }
    }
}

fn run(name: &str, v: &mut Vec<u32>) {
    let n = v.len();
    let t = Instant::now();
    unsafe { core_qsort(v.as_mut_ptr() as *mut u8, n, 4, cmp_key); }
    let el = t.elapsed();
    // 抽查有序性
    let mut ok = true;
    for i in 1..n { if v[i-1] > v[i] { ok = false; break; } }
    println!("{:<22} n={:<8} {:>10.3?}  有序={}", name, n, el, ok);
}

fn main() {
    for n in [10_000usize, 40_000, 160_000] {
        // 1) 全部相等（最坏形态：局部符号空名字）
        let mut a = vec![7u32; n];
        run("全相等", &mut a);
        // 2) 只有 2 个不同键
        let mut b: Vec<u32> = (0..n).map(|i| (i % 2) as u32).collect();
        run("2 个键", &mut b);
        // 3) 随机（对照）
        let mut s = 12345u32;
        let mut c: Vec<u32> = (0..n).map(|_| { s ^= s << 13; s ^= s >> 17; s ^= s << 5; s }).collect();
        run("随机", &mut c);
        // 4) 已升序
        let mut d: Vec<u32> = (0..n as u32).collect();
        run("已升序", &mut d);
        println!();
    }
}
