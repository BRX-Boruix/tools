/* hello_cc1.c —— 端到端验收：cc1 编出 .s，tcc 汇编+链接，在 Boruix 内运行。
 * 不 include 任何头（cc1 没有系统头），自己声明 printf。 */
extern int printf(const char *fmt, ...);

int main(void) {
    int i;
    for (i = 0; i < 3; i++) {
        printf("hello from cc1 in Boruix: i=%d\n", i);
    }
    return 0;
}
