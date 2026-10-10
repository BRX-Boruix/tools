/* 3P 缺陷 12 的最小复现：把真实 JIT 运行时的**探测序列**在机内跑一遍，
 * 记录 BORUIX 对每一种探测的**回答**（而不是猜）。
 *
 * 三类探测对应现实中的三类 JIT：
 *   P1  W^X 型（V8/JSC 硬化平台、LuaJIT 硬模式）：RW 写码 → mprotect RX → 执行
 *   P2  RWX 型（老式 LuaJIT、部分 .NET 路径）：一次 mmap(RWX) 后直接执行
 *   P3  门禁探测：已 RX 的页能否再被 mprotect 成 W+X（W^X 单点是否只有一处）
 *
 * **为什么整篇报告攒在一个缓冲里、最后只 write() 一次**：本系统的控制台是多进程共用
 * 的，逐行 printf 会被别的进程（实测是 intel-hda 的日志）从**行中间**插进去，把证据切碎。
 * 单次 write 让整篇报告在控制台上连续出现——这是取证纪律，不是优化。
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <sys/mman.h>
#include <unistd.h>

typedef int (*fn_t)(void);

/* mov eax, 42 ; ret */
static const unsigned char code42[] = { 0xB8, 0x2A, 0x00, 0x00, 0x00, 0xC3 };
#define PAGE 4096

static char buf[4096];
static unsigned long off;

static void add(const char *s) {
    unsigned long n = (unsigned long)strlen(s);
    if (off + n + 1 >= sizeof buf) {
        return;
    }
    memcpy(buf + off, s, n);
    off += n;
    buf[off] = 0;
}

static void addn(const char *label, long v) {
    char t[96];
    snprintf(t, sizeof t, "%s%ld\n", label, v);
    add(t);
}

static void addp(const char *label, const void *p) {
    char t[96];
    snprintf(t, sizeof t, "%s%p\n", label, p);
    add(t);
}

int main(void) {
    unsigned char *p;
    unsigned char *q;
    int rc;

    /* ---- P1: W^X 型 JIT 的标准路径 ---- */
    errno = 0;
    p = (unsigned char *)mmap(0, PAGE, PROT_READ | PROT_WRITE,
                              MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    addp("P1 mmap(RW)   = ", (void *)p);
    addn("P1 mmap errno = ", errno);
    if (p == MAP_FAILED) {
        add("P1 SKIP (no RW mapping)\n");
    } else {
        memcpy(p, code42, sizeof code42);
        errno = 0;
        rc = mprotect(p, PAGE, PROT_READ | PROT_EXEC);
        addn("P1 mprotect(RX) rc = ", rc);
        addn("P1 mprotect errno  = ", errno);
        if (rc == 0) {
            addn("P1 exec (expect 42) = ", ((fn_t)(void *)p)());
        }
    }

    /* ---- P2: RWX 一次性映射 ---- */
    errno = 0;
    q = (unsigned char *)mmap(0, PAGE, PROT_READ | PROT_WRITE | PROT_EXEC,
                              MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    addp("P2 mmap(RWX)  = ", (void *)q);
    addn("P2 mmap errno = ", errno);
    if (q != MAP_FAILED) {
        memcpy(q, code42, sizeof code42);
        addn("P2 exec (expect 42) = ", ((fn_t)(void *)q)());
    }

    /* ---- P3: 已 RX 的页再要 W+X（门禁是否只有一处） ---- */
    if (p != MAP_FAILED) {
        errno = 0;
        rc = mprotect(p, PAGE, PROT_READ | PROT_WRITE | PROT_EXEC);
        addn("P3 mprotect(RWX) rc = ", rc);
        addn("P3 mprotect errno  = ", errno);
    }

    add("jitprobe: done\n");
    (void)write(1, buf, off);
    return 0;
}
