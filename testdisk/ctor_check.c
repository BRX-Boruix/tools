/* 3P 缺陷 8 的最小复现：clang shim（硬编码 -O2）下 C 构造器是否真的被注册。
 * 红：.init_array/.ctors 里没有条目 => 构造器不会跑。
 * 绿：条目存在且 main 运行时 ctor_ran==1。 */
#include <stdio.h>

static volatile int ctor_ran = 0;
static volatile int ctor_b_ran = 0;

__attribute__((constructor)) static void ctor_a(void) { ctor_ran = 1; }
__attribute__((constructor)) static void ctor_b(void) { ctor_b_ran = 1; }

int main(void) {
    printf("ctor_check: a=%d b=%d\n", (int)ctor_ran, (int)ctor_b_ran);
    return (ctor_ran && ctor_b_ran) ? 0 : 1;
}
