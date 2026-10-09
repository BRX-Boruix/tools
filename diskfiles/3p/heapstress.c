/* heapstress.c —— 用户态分配器的压力 + 完整性验收（在 Boruix 内运行）。
 *
 * 为什么需要它：cc1 在 `during GIMPLE pass: cfg` 段错误，首要嫌疑是 malloc/realloc/free
 * 在"大量小块 + 反复扩缩"的模式下出错——而 libcc1 的 malloc 覆盖不到那种模式。
 * 本程序用**可校验的模式**：每块按 (i,j) 填字节，反复 free/realloc/校验，
 * realloc 后还要确认**前缀内容被保留**（C 契约）。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

#define N 4096
static unsigned char *p[N];
static unsigned len[N];

static unsigned rng = 12345u;
static unsigned rnd(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }
static unsigned char pat(int i, unsigned j) { return (unsigned char)((i * 31u + j * 7u) & 0xffu); }

int main(void) {
    int fails = 0;
    for (int i = 0; i < N; i++) { p[i] = NULL; len[i] = 0; }
    for (int round = 0; round < 300; round++) {
        for (int k = 0; k < 64; k++) {
            int i = (int)(rnd() % N);
            unsigned op = rnd() % 3u;
            if (op == 0) {
                if (p[i]) { free(p[i]); p[i] = NULL; len[i] = 0; }
            } else if (op == 1) {
                unsigned oldlen = len[i];
                unsigned n = 1 + (rnd() % 4000u);
                unsigned char *q = (unsigned char *)realloc(p[i], n);
                if (!q) { printf("FAIL realloc NULL i=%d n=%u\n", i, n); fails++; continue; }
                /* **只校验 min(旧长度, 新长度)**：C 标准对 realloc 只保证这么多字节被保留；
                 * 缩小之后超出新尺寸的尾部允许被改写（本实现会毒化成 0xDD）。
                 * 首版校验了全部旧长度 —— 报出成千上万个**假失败**，把测试自己的错当成了分配器的错。 */
                {
                    unsigned keep = oldlen < n ? oldlen : n;
                    for (unsigned j = 0; j < keep; j++) {
                        if (q[j] != pat(i, j)) { printf("FAIL realloc 丢前缀 i=%d j=%u keep=%u\n", i, j, keep); fails++; break; }
                    }
                }
                p[i] = q; len[i] = n;
                for (unsigned j = 0; j < n; j++) p[i][j] = pat(i, j);
            } else {
                if (p[i]) {
                    for (unsigned j = 0; j < len[i]; j++) {
                        if (p[i][j] != pat(i, j)) { printf("FAIL 内容被改 i=%d j=%u\n", i, j); fails++; break; }
                    }
                }
            }
        }
    }
    for (int i = 0; i < N; i++) if (p[i]) free(p[i]);

    /* ---- mmap 探针：POSIX 要求匿名映射返回**零填充**页，而 GCC 的 ggc 完全依赖这一点
     *      （ggc-page 用 mmap 拿页组，然后假设内容为 0）。若内核没清零，cc1 会读到垃圾指针
     *      ⇒ 正是"GIMPLE CFG pass 段错误"的形状。这里直接验。 ---- */
    {
        const unsigned long LEN = 1UL << 20;
        void *m = mmap(NULL, LEN, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (m == MAP_FAILED) {
            printf("FAIL mmap 失败\n"); fails++;
        } else {
            unsigned char *b = (unsigned char *)m;
            unsigned long j;
            for (j = 0; j < LEN; j++) {
                if (b[j] != 0) { printf("FAIL mmap 页非零 j=%lu v=%u\n", j, (unsigned)b[j]); fails++; break; }
            }
            if (j == LEN) printf("ok   mmap 1MiB 全零\n");
            munmap(m, LEN);
        }
        /* 反复映射/解除映射：ggc 会做很多次，检查地址不重叠、内容独立。 */
        void *a = mmap(NULL, 65536, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        void *b2 = mmap(NULL, 65536, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (a == MAP_FAILED || b2 == MAP_FAILED) { printf("FAIL 连续 mmap 失败\n"); fails++; }
        else {
            memset(a, 0xAA, 65536); memset(b2, 0x55, 65536);
            if (((unsigned char *)a)[0] != 0xAA || ((unsigned char *)b2)[0] != 0x55) {
                printf("FAIL 两次 mmap 相互串扰\n"); fails++;
            } else printf("ok   两次 mmap 互不串扰\n");
            munmap(a, 65536); munmap(b2, 65536);
        }
    }

    printf("heapstress: fails=%d\n", fails);
    return fails ? 1 : 0;
}
