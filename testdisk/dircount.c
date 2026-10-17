/* dircount.c —— 数一个目录里有多少条目，并与期望值比较（可判定的断言）。
 *
 * 动机（2026-10 实测缺陷）：libsys::read_dir 用**固定 2048 字节**缓冲且只调一次，
 * 而内核 readdir 是「放不下整条就整体省略」的分页语义、且**没有游标参数**，
 * 调用方取不到下一页 ⇒ 目录大到装不下时被**静默少列**（实测：100 个文件只列出 52 条）。
 * 那是最坏的一类错误——数据看着正常，但少了。
 *
 * 本程序把「有没有少列」变成退出码：got != want 即 FAIL（非 0）。
 * 报告一次性写出（串口多写者会把分行的输出拆碎）。
 */
#include <dirent.h>
#include <stdio.h>
#include <unistd.h>

static int parse_int(const char *s)
{
    int v = 0;
    while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
    return v;
}

int main(int argc, char **argv)
{
    const char *p = argc > 1 ? argv[1] : "/volumes/BORUIX_DATA/bigdir";
    int want = argc > 2 ? parse_int(argv[2]) : -1;
    DIR *d;
    struct dirent *e;
    int n = 0;
    char out[192];
    int k = 0;

    d = opendir(p);
    if (!d) { printf("dircount: opendir(%s) failed\n", p); return 1; }
    while ((e = readdir(d)) != 0) n++;
    closedir(d);

    k += snprintf(out + k, sizeof(out) - k, "dircount %s got=%d want=%d %s\n",
                  p, n, want, (want < 0 || n == want) ? "PASS" : "FAIL");
    { ssize_t w = write(1, out, (unsigned long)k); (void)w; }
    return (want < 0 || n == want) ? 0 : 1;
}
