//! 数学核心的**宿主对照验证器**（B 档：目标 ≤1 ulp）。
//!
//! 做法：`include!` 纯计算核心，与**宿主 glibc 的 libm**（`f64::sin` 等最终调 libm）
//! 在**大样本 + 边界值**上逐点比对，输出**实测最大 ULP 误差**。
//!
//! 编译运行（宿主，秒级）：
//!     rustc -O --edition 2021 verify.rs -o verify.exe && ./verify.exe

include!("../../../libc/src/math_core.rs");

/// 两个 f64 之间的 ULP 距离（同号有限值；跨 0/inf/nan 返回 i64::MAX 表示不可比）。
fn ulp_diff(a: f64, b: f64) -> i64 {
    if a.is_nan() && b.is_nan() { return 0; }
    if a == b { return 0; }
    if !a.is_finite() || !b.is_finite() { return i64::MAX; }
    let ia = a.to_bits() as i64;
    let ib = b.to_bits() as i64;
    let fa = if ia < 0 { i64::MIN - ia } else { ia };
    let fb = if ib < 0 { i64::MIN - ib } else { ib };
    (fa - fb).abs()
}

struct Stat { name: &'static str, n: u64, max_ulp: i64, worst: f64 }

fn check(name: &'static str, ours: fn(f64) -> f64, theirs: fn(f64) -> f64, xs: &[f64]) -> Stat {
    let mut s = Stat { name, n: 0, max_ulp: 0, worst: f64::NAN };
    for &x in xs {
        let a = ours(x);
        let b = theirs(x);
        let d = ulp_diff(a, b);
        s.n += 1;
        if d > s.max_ulp { s.max_ulp = d; s.worst = x; }
    }
    s
}

fn main() {
    // 样本：广泛覆盖 + 边界
    let mut xs: Vec<f64> = Vec::new();
    let mut i = -2000i64;
    while i <= 2000 { xs.push(i as f64 / 16.0); i += 1; }
    let mut j = 1i64;
    while j <= 400 { xs.push(j as f64 / 7.0); xs.push(-(j as f64) / 7.0); j += 1; }
    xs.extend_from_slice(&[0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 2.0, 0.25, 1e-300, 1e300, 1e-15, 1e15,
        3.14159265358979, 1e10, 0.9999999999, 1.0000000001, 123.456, -123.456, 1e-8, 1e8]);
    let mut stats = vec![
        check("fabs",   core_fabs,   |x| x.abs(),   &xs),
        check("floor",  core_floor,  |x| x.floor(), &xs),
        check("ceil",   core_ceil,   |x| x.ceil(),  &xs),
        check("trunc",  core_trunc,  |x| x.trunc(), &xs),
        check("round",  core_round,  |x| x.round(), &xs),
        check("sqrt",   core_sqrt,   |x: f64| x.sqrt(), &xs),
    ];
    let mut fmod_n = 0u64; let mut fmod_max = 0i64; let mut fmod_worst = f64::NAN;
    for &x in &xs { for &y in &[3.0f64, 7.0, 0.1, 2.5, 1e-3] {
        let a = core_fmod(x, y); let b = x % y; let d = ulp_diff(a, b);
        fmod_n += 1; if d > fmod_max { fmod_max = d; fmod_worst = x; } } }
    stats.push(Stat { name: "fmod", n: fmod_n, max_ulp: fmod_max, worst: fmod_worst });
    println!("{:<8} {:>8} {:>10}  {}", "函数", "样本数", "最大ULP", "最差点");
    let mut bad = 0;
    for s in &stats {
        let flag = if s.max_ulp > 1 { "  <== 超 B 档" } else { "" };
        if s.max_ulp > 1 { bad += 1; }
        println!("{:<8} {:>8} {:>10}  {:e}{}", s.name, s.n, s.max_ulp, s.worst, flag);
    }
    println!("\n超 B 档（>1 ulp）的函数数 = {}", bad);
}
