/* fsbench.c —— 直接量「单次文件操作」的真实代价。
 *
 * 动机（2026-10）：系统内 tcc 的链接慢。细分剖面显示 elf_output_file 里
 * 「section headers」那个循环体只有一句 fwrite(sh, 1, 64, f) 却花了 ~35 秒，
 * 「section data」~74 秒。若每次 fwrite 就是一次 write 系统调用，则 35 秒只能来自
 * 「循环次数极多」或「每次系统调用极慢」。本程序把这两个乘数**分别**量出来。
 *
 * 用 rdtsc（单调、无需头文件）。结果按 cycles/op 打印，便于与 ~3.3GHz 换算。
 */
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <boruix.h>

static unsigned long long tsc(void)
{
    unsigned int lo, hi;
    __asm__ __volatile__("rdtsc" : "=a"(lo), "=d"(hi));
    return ((unsigned long long)hi << 32) | lo;
}

#define N  2000
#define SZ 64
static char buf[SZ];

int main(void)
{
    int fd, i;
    unsigned long long t0, t1;
    const char *path = "/volumes/BORUIX_DATA/fsbench.tmp";

    /* 纯用户态循环作对照：证明 rdtsc 与循环本身的开销可忽略 */
    t0 = tsc();
    for (i = 0; i < N; i++) buf[0]++;
    t1 = tsc();
    printf("loop   %d iters        : %12llu cycles (%llu/op)\n", N, t1 - t0, (t1 - t0) / N);

    fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) { printf("fsbench: open(w) failed\n"); return 1; }
    t0 = tsc();
    for (i = 0; i < N; i++) write(fd, buf, SZ);
    t1 = tsc();
    printf("write  %4d x %d bytes : %12llu cycles (%llu/op)\n", N, SZ, t1 - t0, (t1 - t0) / N);
    close(fd);

    fd = open(path, O_RDONLY, 0);
    if (fd < 0) { printf("fsbench: open(r) failed\n"); return 1; }
    t0 = tsc();
    for (i = 0; i < N; i++) read(fd, buf, SZ);
    t1 = tsc();
    printf("read   %4d x %d bytes : %12llu cycles (%llu/op)\n", N, SZ, t1 - t0, (t1 - t0) / N);
    close(fd);

    /* 单次大块写/读作对照：区分「每次调用固定开销」与「每字节成本」 */
    fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    t0 = tsc();
    write(fd, buf, SZ);
    t1 = tsc();
    printf("write  1 x %d bytes    : %12llu cycles\n", SZ, t1 - t0);
    close(fd);

    /* 关键对照：同样的 2000 次 64 字节写，但**经 stdio 缓冲层**（fopen/fwrite）。
       若缓冲生效，这一行应比上面的裸 write 快几个数量级；若几乎一样，
       说明缓冲没生效（每次 fwrite 仍是一次系统调用）。 */
    {
        FILE *sf = fopen(path, "wb");
        if (sf) {
            unsigned long w0 = boruix_stdio_write_calls();
            unsigned long b0 = boruix_stdio_write_bytes();
            t0 = tsc();
            for (i = 0; i < N; i++) fwrite(buf, 1, SZ, sf);
            fflush(sf);
            t1 = tsc();
            printf("fwrite %4d x %d bytes : %12llu cycles (%llu/op)\n", N, SZ, t1 - t0, (t1 - t0) / N);
            /* **可观察真值**：缓冲若生效，2000 次 fwrite 应只产生约 N*SZ/4096 = 32 次底层写。 */
            printf("      底层 write 次数 = %lu, 字节 = %lu (期望约 %d 次 / %d 字节)\n",
                   boruix_stdio_write_calls() - w0,
                   boruix_stdio_write_bytes() - b0,
                   (N * SZ) / 4096 + 1, N * SZ);
            fclose(sf);
        } else {
            printf("fsbench: fopen failed\n");
        }
    }

    printf("fsbench: done\n");
    return 0;
}
