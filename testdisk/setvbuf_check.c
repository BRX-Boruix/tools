/* setvbuf_check.c —— setvbuf/setbuf 与 clock_gettime(CLOCK_MONOTONIC) 的机内验收。
 *
 * 为什么需要：setvbuf 此前是「刻意的空操作」，理由写的是「本 libc 的 stdio 不做用户态
 * 缓冲」——该前提在写侧缓冲层落地后已不成立，空操作于是从「诚实」退化成**能力谎言**：
 * 调用方请求有缓冲、拿到 0，实际每次仍直写内核。
 *
 * 本程序用底层写调用计数（boruix_stdio_write_calls）把「有没有真的缓冲」变成可观测量：
 * 修复前第 2 条断言必红（20 B 也会立刻产生一次底层写）。
 */
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <wchar.h>
#include <boruix.h>

static int fails = 0;
static void chk(const char *what, int ok) {
    if (!ok) { fails++; printf("FAIL %s\n", what); } else { printf("ok   %s\n", what); }
}

int main(void) {
    unsigned long c0, c1;
    char ubuf[64];
    char data[200];
    int i;
    for (i = 0; i < 200; i++) data[i] = (char)('a' + (i % 26));

    FILE *f = fopen("/volumes/BORUIX_DATA/svb.txt", "w");
    if (!f) { printf("FAIL fopen\n"); return 1; }

    /* 1) 显式无缓冲：每次 fwrite 都应落到内核。 */
    chk("setvbuf(_IONBF) rc=0", setvbuf(f, NULL, _IONBF, 0) == 0);
    c0 = boruix_stdio_write_calls();
    fwrite(data, 1, 100, f);
    c1 = boruix_stdio_write_calls();
    chk("_IONBF: fwrite 100B 至少一次底层写", c1 > c0);

    /* 2) 全缓冲 32 字节：20 字节必须留在用户态缓冲里（0 次底层写）。 */
    chk("setvbuf(_IOFBF,32) rc=0", setvbuf(f, NULL, _IOFBF, 32) == 0);
    c0 = boruix_stdio_write_calls();
    fwrite(data, 1, 20, f);
    c1 = boruix_stdio_write_calls();
    chk("_IOFBF 32: 20B 不落盘（0 次底层写）", c1 == c0);

    /* 3) fflush 必须把它落盘（恰好一次）。 */
    c0 = boruix_stdio_write_calls();
    fflush(f);
    c1 = boruix_stdio_write_calls();
    chk("fflush 落盘一次", c1 == c0 + 1);

    /* 4) 调用方自带缓冲：必须被使用，且不得被本库释放。 */
    memset(ubuf, 0, sizeof ubuf);
    chk("setvbuf(用户缓冲,64) rc=0", setvbuf(f, ubuf, _IOFBF, 64) == 0);
    c0 = boruix_stdio_write_calls();
    fwrite(data, 1, 10, f);
    c1 = boruix_stdio_write_calls();
    chk("用户缓冲: 10B 不落盘", c1 == c0);
    chk("用户缓冲真的被写到", memcmp(ubuf, data, 10) == 0);
    fflush(f);

    /* 5) 只读流请求有缓冲必须如实失败（读侧无缓冲层）。 */
    chk("只读流 _IOFBF 如实失败", setvbuf(stdin, NULL, _IOFBF, 64) != 0);

    /* 6) setbuf(NULL) = 无缓冲。 */
    setbuf(f, NULL);
    c0 = boruix_stdio_write_calls();
    fwrite(data, 1, 7, f);
    c1 = boruix_stdio_write_calls();
    chk("setbuf(NULL) 后 7B 直接落盘", c1 > c0);
    fclose(f);

    /* 7) 内容正确性：100+20+10+7 = 137 字节。 */
    FILE *g = fopen("/volumes/BORUIX_DATA/svb.txt", "r");
    chk("回读打开", g != NULL);
    if (g) {
        long n = 0;
        while (fgetc(g) != EOF) n++;
        fclose(g);
        chk("文件长度 137", n == 137);
    }

    /* 8) clock_gettime(CLOCK_MONOTONIC)：可读、单调推进、其余时钟仍如实。 */
    {
        struct timespec t0, t1;
        int rc0 = clock_gettime(CLOCK_MONOTONIC, &t0);
        chk("clock_gettime(MONOTONIC) rc=0", rc0 == 0);
        int spins = 0;
        do {
            clock_gettime(CLOCK_MONOTONIC, &t1);
            spins++;
        } while (rc0 == 0 && t1.tv_sec == t0.tv_sec && t1.tv_nsec == t0.tv_nsec && spins < 2000);
        chk("MONOTONIC 单调推进", rc0 == 0 && (t1.tv_sec > t0.tv_sec || t1.tv_nsec > t0.tv_nsec));
        chk("REALTIME 仍可用", clock_gettime(CLOCK_REALTIME, &t1) == 0);
        chk("未知时钟如实失败", clock_gettime(99, &t1) != 0);
    }

    /* 9) wcwidth/wcswidth：libc 提供真实 Unicode 宽度表（此前只有各程序私有的近似表）。 */
    chk("wcwidth(0x41 A)==1", wcwidth(0x41) == 1);
    chk("wcwidth(0x4E2D 中)==2", wcwidth(0x4E2D) == 2);
    chk("wcwidth(0x0301 组合)==0", wcwidth(0x0301) == 0);
    chk("wcwidth(0x000A)==-1", wcwidth(0x000A) == -1);
    chk("wcwidth(0x1F600 绘文字)==2", wcwidth(0x1F600) == 2);
    chk("wcwidth(0xFF21 全角 A)==2", wcwidth(0xFF21) == 2);
    chk("wcwidth(0x00E9 e-acute)==1", wcwidth(0x00E9) == 1);
    chk("wcwidth(0x20000 CJK-B)==2", wcwidth(0x20000) == 2);
    {
        wchar_t ws[4];
        ws[0] = 0x41; ws[1] = 0x4E2D; ws[2] = 0x6587; ws[3] = 0;
        chk("wcswidth(A中文)==5", wcswidth(ws, 4) == 5);
    }

    printf("setvbuf_check: fails=%d\n", fails);
    return fails ? 1 : 0;
}