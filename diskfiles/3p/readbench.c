/* readbench.c —— 量「顺序读一个 5 MB 文件」的**裸吞吐**。
 *
 * 动机（2026-10）：tcc 链接里最大的一块是读 libc.a（约 4.7 MB，5~7 秒）。
 * 这一条把「读这些字节本身要多久」从 tcc 的解析逻辑里分出来，
 * 好判断剩下的时间该往内核 I/O 路径还是 tcc 侧找。
 * 用 rdtsc（单调、免头文件）；~3.3 GHz 换算。
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

int main(void)
{
    const char *p = "/volumes/BORUIX_DATA/3p/tcc/libc.a";
    int fd = open(p, O_RDONLY, 0);
    unsigned long long t0, t1, total = 0;
    long n;
    int calls = 0;
    if (fd < 0) { printf("readbench: open failed\n"); return 1; }
    t0 = tsc();
    while ((n = read(fd, buf, sizeof buf)) > 0) { total += (unsigned long long)n; calls++; }
    t1 = tsc();
    close(fd);
    printf("readbench bytes=%llu calls=%d cycles=%llu cyc_per_byte=%llu\n",
           total, calls, t1 - t0, total ? (t1 - t0) / total : 0);
    return 0;
}
