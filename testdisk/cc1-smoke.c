/* cc1-smoke.c —— host=boruix 的 cc1 **在 Boruix 内**运行的最小验收输入。
 *
 * **为什么不用带 <stdio.h> 的文件**：本次构建是 `--target=x86_64-elf --without-headers`，
 * 系统内也没有 GCC 自己的 include/ 目录 ⇒ 只能编**无包含**的翻译单元。
 * 这不是"降级验收"：能对一个真实 C 翻译单元做完词法/语法/语义/优化/汇编输出，
 * 就证明了 cc1 这个几十 MB 的 C++ 程序在 Boruix 上真的跑起来了。
 *
 * **诚实边界**：这一步只到 `.s`——系统内**没有汇编器与链接器**（binutils 未移植），
 * 故 `cc1 x.c -o x` 的全链路尚未达成。见 docs/TODO/3p.md 的 3P6-3。
 *
 * 正本在此；跑 QEMU 前由脚本拷到数据盘（不手工写第二份）。
 */
static int add(int a, int b) { return a + b; }
static int square(int x) { return x * x; }

int compute(int n) {
    int s = 0;
    for (int i = 0; i < n; i++)
        s += square(i) + add(i, 1);
    return s;
}

int main(void) {
    return compute(4);
}
