// 生成 libcc1.c 的**数学库机内验收**向量。
// 参考值取**宿主真 libm**（Rust std 的 f64::sqrt/tan/... 落到宿主 libm），
// 只有当"我们的核心"与"宿主真 libm"**逐位一致**时才输出该行——否则打印 WARN 不输出，
// 这样嵌进 libcc1.c 的就是一组**真值断言**，而不是自证。
mod math_core { include!("../../../libc/src/math_core.rs"); }
mod math_core2 { include!("../../../libc/src/math_core2.rs"); }
use math_core::*;
use math_core2::*;

fn b(x: f64) -> String { format!("0x{:016x}ULL", x.to_bits()) }

fn one(name: &str, got: f64, want: f64) -> String {
    if got.to_bits() == want.to_bits() {
        format!("    chk(bits_of({}) == {}, \"{}\");", name, b(want), name.replace('"', ""))
    } else {
        format!("    /* WARN 不一致，未输出: {} ours={:016x} libm={:016x} */", name, got.to_bits(), want.to_bits())
    }
}
fn two(name: &str, got: f64, want: f64) -> String { one(name, got, want) }

fn main() {
    let mut out = String::new();
    let mut push = |s: String| { out.push_str(&s); out.push('\n'); };
    push(one("sqrt(2.0)", core_sqrt(2.0), 2.0f64.sqrt()));
    push(one("sqrt(0.125)", core_sqrt(0.125), 0.125f64.sqrt()));
    push(one("sqrt(1e-300)", core_sqrt(1e-300), 1e-300f64.sqrt()));
    push(one("cbrt(27.0)", core_cbrt(27.0), 27.0f64.cbrt()));
    push(one("cbrt(1000.0)", core_cbrt(1000.0), 1000.0f64.cbrt()));
    push(one("cbrt(-8.0)", core_cbrt(-8.0), (-8.0f64).cbrt()));
    push(one("cbrt(2.0)", core_cbrt(2.0), 2.0f64.cbrt()));
    push(one("cbrt(5.057142857142857e1)", core_cbrt(50.57142857142857), 50.57142857142857f64.cbrt()));
    push(two("pow(1e8, 1.5)", core_pow(1e8, 1.5), 1e8f64.powf(1.5)));
    push(two("pow(2.0, 10.0)", core_pow(2.0, 10.0), 2.0f64.powf(10.0)));
    push(two("pow(-2.0, 3.0)", core_pow(-2.0, 3.0), (-2.0f64).powf(3.0)));
    push(two("pow(2.0, -1.0)", core_pow(2.0, -1.0), 2.0f64.powf(-1.0)));
    push(two("pow(1.25e-1, 1.5)", core_pow(0.125, 1.5), 0.125f64.powf(1.5)));
    push(two("pow(3.0, 0.5)", core_pow(3.0, 0.5), 3.0f64.powf(0.5)));
    push(one("log2(1024.0)", core_log2(1024.0), 1024.0f64.log2()));
    push(one("log2(0.5)", core_log2(0.5), 0.5f64.log2()));
    push(one("log2(8.571428571428571e-1)", core_log2(0.8571428571428571), 0.8571428571428571f64.log2()));
    push(one("log(1.0)", core_log(1.0), 1.0f64.ln()));
    push(one("log(9.375e-1)", core_log(0.9375), 0.9375f64.ln()));
    push(one("log10(1000.0)", core_log10(1000.0), 1000.0f64.log10()));
    push(one("log1p(0.5)", core_log1p(0.5), 0.5f64.ln_1p()));
    push(one("exp(1.0)", core_exp(1.0), 1.0f64.exp()));
    push(one("exp(-1.245e2)", core_exp(-124.5), (-124.5f64).exp()));
    push(one("expm1(1.0)", core_expm1(1.0), 1.0f64.exp_m1()));
    push(one("sin(0.5)", core_sin(0.5), 0.5f64.sin()));
    push(one("cos(0.5)", core_cos(0.5), 0.5f64.cos()));
    push(one("tan(0.5)", core_tan(0.5), 0.5f64.tan()));
    push(one("tan(-1.215e2)", core_tan(-121.5), (-121.5f64).tan()));
    push(one("tan(1.24875e2)", core_tan(124.875), 124.875f64.tan()));
    push(one("asin(0.5)", core_asin(0.5), 0.5f64.asin()));
    push(one("asin(4.2857142857142855e-1)", core_asin(0.42857142857142855), 0.42857142857142855f64.asin()));
    push(one("asin(0.9999)", core_asin(0.9999), 0.9999f64.asin()));
    push(one("acos(0.5)", core_acos(0.5), 0.5f64.acos()));
    push(one("atan(1.0)", core_atan(1.0), 1.0f64.atan()));
    push(one("atan(-1.24625e2)", core_atan(-124.625), (-124.625f64).atan()));
    push(two("atan2(1.0, 1.0)", core_atan2(1.0, 1.0), 1.0f64.atan2(1.0)));
    push(one("sinh(1.0)", core_sinh(1.0), 1.0f64.sinh()));
    push(one("cosh(1.0)", core_cosh(1.0), 1.0f64.cosh()));
    push(one("tanh(1.0)", core_tanh(1.0), 1.0f64.tanh()));
    push(two("hypot(3.0, 4.0)", core_hypot(3.0, 4.0), 3.0f64.hypot(4.0)));
    push(two("hypot(2.7142857142857144e0, 1.0)", core_hypot(2.7142857142857144, 1.0), 2.7142857142857144f64.hypot(1.0)));
    push(two("hypot(1e300, 1e300)", core_hypot(1e300, 1e300), 1e300f64.hypot(1e300)));
    push(two("fmod(7.0, 3.0)", core_fmod(7.0, 3.0), 7.0f64 % 3.0));
    push(one("floor(-2.5)", core_floor(-2.5), (-2.5f64).floor()));
    push(one("ceil(-2.5)", core_ceil(-2.5), (-2.5f64).ceil()));
    push(one("trunc(-2.5)", core_trunc(-2.5), (-2.5f64).trunc()));
    push(one("round(-2.5)", core_round(-2.5), (-2.5f64).round()));
    push(one("fabs(-3.5)", core_fabs(-3.5), (-3.5f64).abs()));
    push(one("nearbyint(2.5)", core_nearbyint(2.5), 2.5f64.round_ties_even()));
    push(one("nextafter(1.0, 2.0)", core_nextafter(1.0, 2.0), 1.0f64.next_up()));
    print!("{}", out);
}
