/* readbench.c —— 量「顺序读一个 5 MB 文件」的**裸吞吐**，并给出设备命令计数。
 *
 * 动机（2026-10）：tcc 链接里最大的一块是读 libc.a（约 4.7 MB，5~7 秒）。
 * 这一条把「读这些字节本身要多久」从 tcc 的解析逻辑里分出来。
 * 第二轮读同一文件：用来判断块缓存对 5 MB > 2 MiB 缓存的顺序读到底有没有用。
 * 用 rdtsc（单调、免头文件）；~3.3 GHz 换算。报告一次性写出。
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
static char rep[4096];
static int rn;
static void app(const char *s) { while (*s && rn < 4095) rep[rn++] = *s++; }

static void snap(const char *tag)
{
    int fd = open("/devices/storage/cache", O_RDONLY);
    int n, i;
    app(tag);
    if (fd < 0) { app(" open-failed\n"); return; }
    n = read(fd, buf, 1024);
    close(fd);
    if (n < 0) n = 0;
    for (i = 0; i < n; i++) rep[rn++] = (buf[i] == 10 || buf[i] == 13) ? 32 : buf[i];
    app("\n");
}

static void pass(const char *tag)
{
    const char *p = "/volumes/BORUIX_DATA/3p/tcc/libc.a";
    int fd = open(p, O_RDONLY, 0);
    unsigned long long t0, t1, total = 0;
    long n;
    int calls = 0;
    if (fd < 0) { app("readbench: open failed\n"); return; }
    snap("[readbench] before ");
    t0 = tsc();
    while ((n = read(fd, buf, sizeof buf)) > 0) { total += (unsigned long long)n; calls++; }
    t1 = tsc();
    close(fd);
    snap("[readbench] after  ");
    printf("readbench %s bytes=%llu calls=%d cycles=%llu cyc_per_byte=%llu\n",
           tag, total, calls, t1 - t0, total ? (t1 - t0) / total : 0);
}

int main(void)
{
    pass("pass1");
    pass("pass2");
    { ssize_t w = write(1, rep, (size_t)rn); (void)w; }
    return 0;
}
