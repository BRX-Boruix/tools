/* mathclass_check.c —— C99 浮点分类的机内验收。
 *
 * 为什么需要：本 libc 的 <math.h> 此前**只有 FP_* 常量**，六个分类入口一个都没有
 * （3P6-3 记录的真实阻塞）。修复前本程序**编译/链接不过**。
 *
 * 形态说明：C99 规定它们是宏；本 libc 提供**函数**（机内 tcc 不提供 __builtin_*，
 * 实测 8 条 unresolved reference），故这里直接调函数。
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

static int fails = 0;
static void chk(const char *what, int ok) {
    if (!ok) { fails++; printf("FAIL %s\n", what); } else { printf("ok   %s\n", what); }
}

int main(void) {
    /* 不用 NAN/INFINITY 宏：它们在本 libc 里是 `__builtin_nanf`/`__builtin_inff`，
     * 而机内 tcc **不提供这些内建**（实测 unresolved reference）——那是一个**独立的**
     * 既有缺陷，已另行登记。本程序改用 strtod 取得 NaN/无穷，只验分类函数本身。 */
    /* 两条路都堵着，故用**运行时 IEEE 除法**造 NaN/无穷：
     * - NAN/INFINITY 宏是 `__builtin_nanf`/`__builtin_inff`，tcc 没有这些内建；
     * - `strtod("nan"/"inf")` 在本 libc 里**不认这两个字符串**（实测 6 条断言全红）。
     * 两者都是**独立的既有缺陷**，已另行登记；此处只验分类函数本身。
     * `volatile` 是关键：阻止编译期常量折叠，强制走运行时 IEEE 语义。 */
    volatile double zero = 0.0;
    double nan_v = zero / zero;
    double inf_v = 1.0 / zero;
    double neg_inf = -1.0 / zero;
    double sub = 4.9406564584124654e-324;   /* DBL_TRUE_MIN：次正规数 */
    double one = 1.0;
    double neg_zero = -0.0;
    float  fzero = 0.0f;

    chk("isnan(NAN)", isnan(nan_v) != 0);
    chk("!isnan(1.0)", isnan(one) == 0);
    chk("isinf(INFINITY)==1", isinf(inf_v) == 1);
    chk("isinf(-INFINITY)==-1", isinf(neg_inf) == -1);
    chk("isfinite(1.0)", isfinite(one) != 0);
    chk("!isfinite(INFINITY)", isfinite(inf_v) == 0);
    chk("isnormal(1.0)", isnormal(one) != 0);
    chk("!isnormal(0.0)", isnormal(0.0) == 0);
    chk("signbit(-1.0)", signbit(-1.0) != 0);
    chk("signbit(-0.0)", signbit(neg_zero) != 0);
    chk("!signbit(1.0)", signbit(one) == 0);
    chk("fpclassify(NAN)==FP_NAN", fpclassify(nan_v) == FP_NAN);
    chk("fpclassify(INFINITY)==FP_INFINITE", fpclassify(inf_v) == FP_INFINITE);
    chk("fpclassify(0.0)==FP_ZERO", fpclassify(0.0) == FP_ZERO);
    chk("fpclassify(1.0)==FP_NORMAL", fpclassify(one) == FP_NORMAL);
    chk("fpclassify(次正规)==FP_SUBNORMAL", fpclassify(sub) == FP_SUBNORMAL);
    (void)0;
    chk("float 实参可用（隐式转换）", fpclassify(fzero) == FP_ZERO);

    printf("mathclass_check: fails=%d\n", fails);
    return fails ? 1 : 0;
}