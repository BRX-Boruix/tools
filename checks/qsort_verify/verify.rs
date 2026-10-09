// qsort_core 的**宿主对照测试**：与 Rust 参考排序逐点比对。
// 为什么要有它：qsort 的越界读只在特定数据上触发，而"在 QEMU 里跑 cc1"要 8 分钟且只给
// 一个"段错误"的弱信号。这里用大量随机/退化输入在秒级抓出。
use core::ffi::{c_int, c_void};

#[path = "../../../libc/src/qsort_core.rs"]
mod qsort_core;
use qsort_core::core_qsort;

// 确定性 PRNG（xorshift64*），保证可复现。
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12; x ^= x << 25; x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545F4914F6CDD1D)
    }
}

// 按元素宽度比较：统一用"取前 8 字节当小端 u64"的键，参考排序用同一把键 ⇒ 语义一致。
// **比较键只能读元素实际有的字节**：首版固定读 8 字节，size=4 时会读到下一个元素，
// 于是"参考排序"与"被测排序"用的键不同 —— 报出 122 个**假失败**。测试自己先要正确。
static mut CUR_SIZE: usize = 8;

unsafe extern "C" fn cmp_key(a: *const c_void, b: *const c_void) -> c_int {
    unsafe {
        let n = CUR_SIZE.min(8);
        let ka = key_n(a, n); let kb = key_n(b, n);
        if ka < kb { -1 } else if ka > kb { 1 } else { 0 }
    }
}
unsafe fn key_n(p: *const c_void, n: usize) -> u64 {
    unsafe {
        let q = p as *const u8;
        let mut v = 0u64;
        for i in 0..n { v |= (*q.add(i) as u64) << (8 * i); }
        v
    }
}

/// 从元素字节里取键——**只读该元素实际有的字节**（size 可能 < 8，首版这里越界 panic 了）。
fn key_of(e: &[u8]) -> u64 {
    let mut v = 0u64;
    for i in 0..8.min(e.len()) { v |= (e[i] as u64) << (8 * i); }
    v
}

fn run_case(name: &str, elems: &[Vec<u8>], size: usize, fails: &mut u32) {
    let n = elems.len();
    let mut buf = vec![0u8; n * size + 8];
    for (i, e) in elems.iter().enumerate() {
        buf[i * size..i * size + e.len()].copy_from_slice(e);
    }
    unsafe { CUR_SIZE = size; }
    let mut want: Vec<Vec<u8>> = elems.to_vec();
    want.sort_by_key(|e| key_of(e));
    unsafe { core_qsort(buf.as_mut_ptr(), n, size, cmp_key); }
    for i in 0..n {
        if buf[i * size..i * size + size] != want[i][..] {
            println!("FAIL {name} n={n} size={size} 第 {i} 个元素不对");
            *fails += 1;
            return;
        }
    }
}

fn main() {
    let mut fails = 0u32;
    let mut rng = Rng(0x1234_5678_9ABC_DEF0);
    for &size in &[1usize, 2, 4, 8, 12, 16, 24, 40, 64] {
        for &n in &[0usize, 1, 2, 3, 5, 12, 13, 20, 33, 64, 100, 257, 500] {
            // 随机
            let mut e = Vec::new();
            for _ in 0..n {
                let mut v = vec![0u8; size];
                let k = rng.next();
                for i in 0..8.min(size) { v[i] = (k >> (8*i)) as u8; }
                e.push(v);
            }
            run_case("随机", &e, size, &mut fails);
            // 已升序
            let mut s = e.clone();
            s.sort_by_key(|x| key_of(x));
            run_case("已升序", &s, size, &mut fails);
            // 已降序
            let mut d = s.clone(); d.reverse();
            run_case("已降序", &d, size, &mut fails);
            // 全相等
            let eq: Vec<Vec<u8>> = (0..n).map(|_| vec![0x5Au8; size]).collect();
            run_case("全相等", &eq, size, &mut fails);
            // 大量重复（只有 3 个不同键）
            let mut r3 = Vec::new();
            for _ in 0..n {
                let k = rng.next() % 3;
                let mut v = vec![0u8; size];
                for i in 0..8.min(size) { v[i] = (k >> (8*i)) as u8; }
                r3.push(v);
            }
            run_case("三值重复", &r3, size, &mut fails);
        }
    }
    println!("qsort_core 宿主对照：fails={fails}");
}
