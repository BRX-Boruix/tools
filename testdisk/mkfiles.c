/* mkfiles.c —— 在一个目录里造 N 个空文件（大目录复现夹具）。
 *
 * 为什么不用 shell 的 touch：本 shell 的 touch 是**单操作数**内建
 * （shell/src/commands.rs 的 cmd_touch(arg) 只取整段余下文本当一个路径），
 * 故 `touch a b c` 会把整串当成一个文件名 ⇒ 造 120 个文件要 120 条命令。
 * 用一个夹具程序更干净，也把「造夹具」与「被测对象」分开。
 */
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>

static int parse_int(const char *s)
{
    int v = 0;
    while (*s >= 48 && *s <= 57) { v = v * 10 + (*s - 48); s++; }
    return v;
}

int main(int argc, char **argv)
{
    const char *dir = argc > 1 ? argv[1] : "/volumes/BORUIX_DATA/bigdir";
    int n = argc > 2 ? parse_int(argv[2]) : 120;
    char path[192];
    char out[96];
    int i, made = 0, k;

    for (i = 0; i < n; i++) {
        int fd;
        snprintf(path, sizeof path, "%s/f%03d", dir, i);
        fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd >= 0) { close(fd); made++; }
    }
    k = snprintf(out, sizeof out, "mkfiles made=%d want=%d\n", made, n);
    { ssize_t w = write(1, out, (unsigned long)k); (void)w; }
    return made == n ? 0 : 1;
}
