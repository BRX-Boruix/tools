/* fswrite.c —— 把「文件写的代价」按**次**还是按**字节**分开量，
 * 并对照「追加（每次分配新块）」与「同偏移覆盖（块已在缓存里）」。
 *
 * 动机（2026-10）：机内剖面显示 tcc 链接的 71% 花在写 ELF 输出上，且
 * 总字节 673,522 / 36.2 秒 ≈ 54 µs/字节。libc 的 stdio 写侧缓冲是 4 KiB
 * （实测 539 次底层 write / 2,048,000 字节）⇒ 一次 4 KiB 的 write ≈ 250 毫秒。
 * 本程序把「每次调用的固定开销」与「每字节成本」分别量出来，并用
 * 「追加 vs 覆盖」判别代价是在**块分配/设备**还是在**拷贝/缓存**路径上。
 *
 * 用 rdtsc（单调、免头文件）；cycles 与 ~3.3 GHz 换算。
 */
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>

static unsigned long long tsc(void)
{
    unsigned int lo, hi;
    __asm__ __volatile__("rdtsc" : "=a"(lo), "=d"(hi));
    return ((unsigned long long)hi << 32) | lo;
}

static char buf[65536];
#define TOTAL 32768

static void sweep(const char *tag, const char *path, int append)
{
    int sizes[5] = {64, 256, 1024, 4096, 16384};
    int s, i;
    printf("%s  path=%s\n", tag, path);
    for (s = 0; s < 5; s++) {
        int sz = sizes[s];
        int cnt = TOTAL / sz;
        int fd;
        unsigned long long t0, t1, d;
        fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd < 0) { printf("  size=%6d  open failed\n", sz); return; }
        if (!append) {
            /* 先把文件按最大尺寸建好，再在偏移 0 处反复覆盖同一段（块已在缓存里）。 */
            for (i = 0; i < TOTAL; i += 4096) write(fd, buf, 4096);
        }
        t0 = tsc();
        for (i = 0; i < cnt; i++) {
            if (append) write(fd, buf, sz);
            else        pwrite(fd, buf, sz, 0);
        }
        t1 = tsc();
        close(fd);
        d = t1 - t0;
        printf("  size=%6d cnt=%5d  %14llu cyc  %12llu cyc/op  %8llu cyc/byte\n",
               sz, cnt, d, d / (unsigned long long)cnt,
               d / (unsigned long long)(cnt * sz));
    }
}

int main(void)
{
    sweep("A 追加（每次分配新块）", "/volumes/BORUIX_DATA/fsw_ap.tmp", 1);
    sweep("B 覆盖（同偏移，块已缓存）", "/volumes/BORUIX_DATA/fsw_ov.tmp", 0);
    sweep("C 追加到 /tmp", "/tmp/fsw_ap.tmp", 1);
    printf("fswrite: done\n");
    return 0;
}
