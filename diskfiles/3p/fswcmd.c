/* fswcmd.c —— 用 /devices/storage/cache 的**设备命令计数**回答一个具体问题：
 * 「追加一个新块」到底发出几条设备命令？
 *
 * 动机（2026-10）：fswrite.c 量到数据盘上的追加写恒为 ~130,000 cycles/字节，
 * 而同偏移覆盖只要 680 cyc/byte、/tmp 只要 742 ⇒ 成本在**新块首次触碰**。
 * 换算约 40 毫秒/新块（1024 B）。ext2 的 alloc_block 每分配一块要碰 superblock、
 * 组描述符、块位图、并把新块清零——若这些**都命中块缓存**，代价应是微秒级；
 * 若它们**每次都落到设备**，40 毫秒/块就正好是几条 ~7 毫秒的命令。
 * 计数是确定性的，没有墙钟那样的运行间波动。
 *
 * 三组同字节数（各 32768 B）的对照：
 *   A 追加 4096 x 8    （32 个新块，8 次系统调用）
 *   B 追加   64 x 512  （32 个新块，512 次系统调用）
 *   C 覆盖 4096 x 8 @0 （0 个新块）
 * A 与 B 命令数相同 ⇒ 按块计价；C 与 A 的差 ⇒ 就是「新块」的价格。
 *
 * 报告**一次性写出**（串口多写者会把分行的输出拆碎）。
 */
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>

#define CAP 4096
static char rep[CAP];
static int rn;

static void app(const char *s) { while (*s && rn < CAP - 1) rep[rn++] = *s++; }

/* 取一份 /devices/storage/cache 快照，压成单行（便于串口留档）。 */
static int snap(char *out, int cap) {
    int fd, n, i;
    fd = open("/devices/storage/cache", O_RDONLY);
    if (fd < 0) { out[0] = 0; return -1; }
    n = read(fd, out, cap - 1);
    close(fd);
    if (n < 0) n = 0;
    out[n] = 0;
    for (i = 0; i < n; i++)
        if (out[i] == 10 || out[i] == 13) out[i] = 32;
    return n;
}

static char buf[16384];

int main(void) {
    char c0[1024], c1[1024], c2[1024], c3[1024], c4[1024], c5[1024];
    const char *p = "/volumes/BORUIX_DATA/fswcmd.tmp";
    int fd, i;

    fd = open(p, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) { app("fswcmd: open failed"); goto out; }

    /* A：追加 32768 B，4096 x 8 */
    snap(c0, sizeof c0);
    for (i = 0; i < 8; i++) write(fd, buf, 4096);
    snap(c1, sizeof c1);

    /* B：同文件再追加 32768 B，64 x 512 */
    lseek(fd, 32768, SEEK_SET);
    snap(c2, sizeof c2);
    for (i = 0; i < 512; i++) write(fd, buf, 64);
    snap(c3, sizeof c3);

    /* C：同偏移覆盖 32768 B，4096 x 8（0 个新块） */
    snap(c4, sizeof c4);
    for (i = 0; i < 8; i++) pwrite(fd, buf, 4096, 0);
    snap(c5, sizeof c5);
    close(fd);

    app("fswcmd A_before "); app(c0); app(" | ");
    app("A_after "); app(c1); app(" | ");
    app("B_before "); app(c2); app(" | ");
    app("B_after "); app(c3); app(" | ");
    app("C_before "); app(c4); app(" | ");
    app("C_after "); app(c5); app(" | ");
out:
    app("fswcmd: done");
    { ssize_t w = write(1, rep, (size_t)rn); (void)w; }
    return 0;
}
