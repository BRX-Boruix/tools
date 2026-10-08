mod math_core { include!("../../../libc/src/math_core.rs"); }
mod math_core2 { include!("../../../libc/src/math_core2.rs"); }
use math_core2::*;

fn show(tag: &str, x: f64) {
    let o = core_sin(x);
    let h = x.sin();
    println!("{:<22} x={:<14} ours={:+.17e} host={:+.17e} diff={:e}", tag, x, o, h, (o - h).abs());
}

fn main() {
    println!("--- 小参数（n=0，纯多项式）---");
    for x in [0.1f64, 0.3, 0.5, 0.7, 0.785] { show("sin small", x); }
    println!("--- n=1 象限（应走 cos_poly）---");
    for x in [1.6f64, 2.0, 2.5, 3.0] { show("sin n=1", x); }
    println!("--- n=2 ---");
    for x in [3.2f64, 4.0, 4.5] { show("sin n=2", x); }
    println!("--- 大参数（归约 + 象限）---");
    for x in [-112.3125f64, -112.0, 100.0, 1000.0] { show("sin big", x); }
    println!("--- cos 对照 ---");
    for x in [0.5f64, 2.0, -112.3125] {
        let o = core_cos(x); let h = x.cos();
        println!("{:<22} x={:<14} ours={:+.17e} host={:+.17e} diff={:e}", "cos", x, o, h, (o - h).abs());
    }
}
