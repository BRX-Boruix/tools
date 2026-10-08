// 数学核心的**宿主对照验证器**（B 档：目标 ≤1 ulp）。
// 用 mod + include! 把 libc 里的**同一份源码**引入，与宿主 glibc 的 libm 逐点比 ULP。
// 运行：rustc -O --edition 2021 verify.rs -o verify.exe && ./verify.exe

mod math_core { include!("../../../libc/src/math_core.rs"); }
mod math_core2 { include!("../../../libc/src/math_core2.rs"); }
use math_core::*;
use math_core2::*;

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

fn run(name: &str, ours: fn(f64) -> f64, theirs: fn(f64) -> f64, xs: &[f64], bad: &mut Vec<String>) {
    let mut max = 0i64; let mut worst = f64::NAN;
    for &x in xs {
        let d = ulp_diff(ours(x), theirs(x));
        if d > max { max = d; worst = x; }
    }
    let flag = if max > 1 { bad.push(name.to_string()); "  <== 超 B 档" } else { "" };
    println!("{:<9} {:>7} {:>9}  {:e}{}", name, xs.len(), max, worst, flag);
}

fn run2(name: &str, ours: fn(f64, f64) -> f64, theirs: fn(f64, f64) -> f64, xs: &[f64], ys: &[f64], bad: &mut Vec<String>) {
    let mut max = 0i64; let mut worst = (f64::NAN, f64::NAN); let mut n = 0u64;
    for &x in xs { for &y in ys {
        let d = ulp_diff(ours(x, y), theirs(x, y));
        n += 1;
        if d > max { max = d; worst = (x, y); }
    } }
    let flag = if max > 1 { bad.push(name.to_string()); "  <== 超 B 档" } else { "" };
    println!("{:<9} {:>7} {:>9}  ({:e},{:e}){}", name, n, max, worst.0, worst.1, flag);
}

fn main() {
    let mut xs: Vec<f64> = Vec::new();
    let mut i = -2000i64;
    while i <= 2000 { xs.push(i as f64 / 16.0); i += 1; }
    let mut j = 1i64;
    while j <= 600 { xs.push(j as f64 / 7.0); xs.push(-(j as f64) / 7.0); j += 1; }
    xs.extend_from_slice(&[0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 2.0, 0.25, 1e-300, 1e300, 1e-15,
        1e15, 3.14159265358979, 1e10, 0.9999999999, 1.0000000001, 123.456, -123.456,
        1e-8, 1e8, 0.1, 0.9, -0.9, 1.5, -1.5, 3.0, 10.0, 100.0, 700.0, -700.0]);
    // exp/log 用正样本为主
    let pos: Vec<f64> = xs.iter().cloned().filter(|&x| x > 0.0).collect();
    let mut bad: Vec<String> = Vec::new();
    println!("{:<9} {:>7} {:>9}  {}", "函数", "样本数", "最大ULP", "最差点");
    run("fabs",   core_fabs,   |x| x.abs(),   &xs, &mut bad);
    run("floor",  core_floor,  |x| x.floor(), &xs, &mut bad);
    run("ceil",   core_ceil,   |x| x.ceil(),  &xs, &mut bad);
    run("trunc",  core_trunc,  |x| x.trunc(), &xs, &mut bad);
    run("round",  core_round,  |x| x.round(), &xs, &mut bad);
    run("sqrt",   core_sqrt,   |x: f64| x.sqrt(), &xs, &mut bad);
    run("cbrt",   core_cbrt,   |x: f64| x.cbrt(), &xs, &mut bad);
    run("exp",    core_exp,    |x: f64| x.exp(), &xs, &mut bad);
    run("expm1",  core_expm1,  |x: f64| x.exp_m1(), &xs, &mut bad);
    run("log",    core_log,    |x: f64| x.ln(), &pos, &mut bad);
    run("log1p",  core_log1p,  |x: f64| x.ln_1p(), &xs, &mut bad);
    run("log2",   core_log2,   |x: f64| x.log2(), &pos, &mut bad);
    run("log10",  core_log10,  |x: f64| x.log10(), &pos, &mut bad);
    let trig: Vec<f64> = xs.iter().cloned().filter(|&x| x.abs() <= 1048576.0).collect();
    run("sin",    core_sin,    |x: f64| x.sin(), &trig, &mut bad);
    run("cos",    core_cos,    |x: f64| x.cos(), &trig, &mut bad);
    run("tan",    core_tan,    |x: f64| x.tan(), &trig, &mut bad);
    run("atan",   core_atan,   |x: f64| x.atan(), &xs, &mut bad);
    run("asin",   core_asin,   |x: f64| x.asin(), &xs, &mut bad);
    run("acos",   core_acos,   |x: f64| x.acos(), &xs, &mut bad);
    run("sinh",   core_sinh,   |x: f64| x.sinh(), &xs, &mut bad);
    run("cosh",   core_cosh,   |x: f64| x.cosh(), &xs, &mut bad);
    run("tanh",   core_tanh,   |x: f64| x.tanh(), &xs, &mut bad);
    run2("atan2", core_atan2,  |y: f64, x: f64| y.atan2(x), &xs, &[1.0, -1.0, 0.5, 2.0, 0.0, -0.0], &mut bad);
    run2("hypot", core_hypot,  |x: f64, y: f64| x.hypot(y), &xs, &[1.0, 2.0, 0.5], &mut bad);
    run2("fmod",  core_fmod,   |x: f64, y: f64| x % y, &xs, &[3.0, 7.0, 0.1, 2.5], &mut bad);
    run2("pow",   core_pow,    |x: f64, y: f64| x.powf(y), &pos, &[2.0, 3.0, 0.5, 1.5, -1.0], &mut bad);
    println!();
    println!("超 B 档（>1 ulp）的函数：{:?}", bad);
    println!("达标函数数 = {} / 27", 27 - bad.len());
}
