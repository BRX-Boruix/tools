/* cowsay.c —— 3P6-4（终局验收）：**系统内编出的新第三方程序**（3P6-5 的第一个源码包）。
 *
 * 它"新"在三处：既不是内核 payload 里那个 Rust 版 cowsay，也不是上游 tcc 的测试用例，
 * 而是为本阶段新写的 C 程序——并且它**在 BORUIX 内被 tcc 编译、在 BORUIX 内运行**。
 *
 * 用法：
 *   cowsay 你好 Boruix              # 消息 = argv[1..] 用空格连接
 *   cowsay -f /path/to/msg.txt      # 消息 = 文件内容（去掉尾部空白）
 *   cowsay -w 30 一段很长的话...    # 折行宽度（显示列数，默认 40）
 *   echo 来自 stdin | cowsay        # 无参数时从 stdin 读一行
 *
 * 退出码：0 成功；1 文件打不开；2 没有消息。
 *
 * ## UTF-8（实测缺陷驱动，不是预猜）
 *
 * 第一版按**字节**折行，于是把多字节字符拦腰截断——实测用它包一份中文文本时，
 * 气泡里出现替换字符与错位。故本版：
 *   - 折行按**显示列数**（东亚宽/全角算 2 列），且**绝不断开**一个 UTF-8 序列；
 *   - 补齐右边界时也按显示列数。
 * 显示列数**统一走 libc 的 `wcwidth`**（S15 单点）。此前这里有一份私有近似表，
 * 注释如实写着「不是完整 wcwidth」——私有表的后果是每个要列宽的程序都得再抄一份。
 * 现在 libc 提供了真正的 `wcwidth`（`libc/src/wcwidth.rs`，区间表 + 边界成文），
 * 本程序只保留「不可打印按 1 列」这一层折行兜底。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define DEF_WIDTH 40
#define MAX_LINES 256
#define MAX_LINE  1024

/* 奶牛的 ASCII 画（与 payload 里那个 Rust 版不同的造型）。 */
static const char *COW[] = {
    "        \\   ^__^",
    "         \\  (oo)\\_______",
    "            (__)\\       )\\/\\",
    "                ||----w |",
    "                ||     ||",
    NULL
};

static char g_lines[MAX_LINES][MAX_LINE];
static int  g_width[MAX_LINES];   /* 每行的**显示列数** */
static int  g_nlines = 0;

/* ---------- UTF-8 小工具 ---------- */

/* 首字节决定序列长度；非法首字节按 1 字节处理（不崩、不吞后续字节）。 */
static int u8_len(unsigned char c) {
    if (c < 0x80) return 1;
    if ((c & 0xE0) == 0xC0) return 2;
    if ((c & 0xF0) == 0xE0) return 3;
    if ((c & 0xF8) == 0xF0) return 4;
    return 1;
}

static unsigned u8_decode(const unsigned char *p, int n) {
    if (n <= 1) return (unsigned)p[0];
    if (n == 2) return ((unsigned)(p[0] & 0x1F) << 6) | (unsigned)(p[1] & 0x3F);
    if (n == 3)
        return ((unsigned)(p[0] & 0x0F) << 12) | ((unsigned)(p[1] & 0x3F) << 6) |
               (unsigned)(p[2] & 0x3F);
    return ((unsigned)(p[0] & 0x07) << 18) | ((unsigned)(p[1] & 0x3F) << 12) |
           ((unsigned)(p[2] & 0x3F) << 6) | (unsigned)(p[3] & 0x3F);
}

/* 显示列数：**统一走 libc 的 `wcwidth`**（S15 单点）。
 *
 * 不可打印字符（`wcwidth` 返回 -1）在折行里按 1 列兜底——折行必须给出一个有限宽度，
 * 而控制字符本就不该出现在消息文本里（真出现了也不该把折行算成负数或 0 列）。 */
static int disp_width(unsigned cp) {
    int w = wcwidth((wchar_t)cp);
    return w < 0 ? 1 : w;
}

/* 从 s 起、最多 max_bytes 字节内，取不超过 max_cols 显示列的整字符前缀。
 * 返回字节数（>0，除非 *s == 0）；*cols 写回实际列数。绝不截断序列。 */
static size_t take_cols(const char *s, size_t max_bytes, int max_cols, int *cols) {
    const unsigned char *p = (const unsigned char *)s;
    size_t used = 0;
    int c = 0;
    while (p[used] && used < max_bytes) {
        int n = u8_len(p[used]);
        int w;
        if (used + (size_t)n > max_bytes)
            break;
        w = disp_width(u8_decode(p + used, n));
        if (c > 0 && c + w > max_cols)
            break;
        c += w;
        used += (size_t)n;
        if (c >= max_cols)
            break;
    }
    if (used == 0 && p[0]) {
        /* 单个字符就超宽：至少放一个，保证前进 */
        used = (size_t)u8_len(p[0]);
        c = disp_width(u8_decode(p, (int)used));
    }
    *cols = c;
    return used;
}

static int span_cols(const char *s, size_t len) {
    const unsigned char *p = (const unsigned char *)s;
    size_t k = 0;
    int c = 0;
    while (k < len) {
        int n = u8_len(p[k]);
        c += disp_width(u8_decode(p + k, n));
        k += (size_t)n;
    }
    return c;
}

static void add_line(const char *s, size_t len, int cols) {
    if (g_nlines >= MAX_LINES)
        return;
    if (len >= MAX_LINE)
        len = MAX_LINE - 1;
    memcpy(g_lines[g_nlines], s, len);
    g_lines[g_nlines][len] = 0;
    g_width[g_nlines] = cols;
    g_nlines++;
}

/* 贪心折行：按**显示列**计宽，空格处优先断行，超宽单词按字符硬断。 */
static void wrap(const char *msg, int width) {
    char cur[MAX_LINE];
    size_t clen = 0;
    int ccols = 0;
    const char *p = msg;

    if (width < 8) width = 8;
    if (width > MAX_LINE / 4) width = MAX_LINE / 4;
    cur[0] = 0;

    while (*p) {
        const char *w;
        size_t wl;
        int wcols;
        while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')
            p++;
        if (!*p)
            break;
        w = p;
        while (*p && *p != ' ' && *p != '\t' && *p != '\n' && *p != '\r')
            p++;
        wl = (size_t)(p - w);
        wcols = span_cols(w, wl);

        if (clen == 0) {
            while (wcols > width) {
                int cols = 0;
                size_t take = take_cols(w, wl, width, &cols);
                add_line(w, take, cols);
                w += take;
                wl -= take;
                wcols -= cols;
            }
            memcpy(cur, w, wl);
            cur[wl] = 0;
            clen = wl;
            ccols = wcols;
        } else if (ccols + 1 + wcols <= width) {
            cur[clen] = ' ';
            memcpy(cur + clen + 1, w, wl);
            clen += 1 + wl;
            ccols += 1 + wcols;
            cur[clen] = 0;
        } else {
            add_line(cur, clen, ccols);
            while (wcols > width) {
                int cols = 0;
                size_t take = take_cols(w, wl, width, &cols);
                add_line(w, take, cols);
                w += take;
                wl -= take;
                wcols -= cols;
            }
            memcpy(cur, w, wl);
            cur[wl] = 0;
            clen = wl;
            ccols = wcols;
        }
    }
    if (clen)
        add_line(cur, clen, ccols);
    if (g_nlines == 0)
        add_line("", 0, 0);
}

static void bubble(void) {
    int maxlen = 0;
    int i;
    for (i = 0; i < g_nlines; i++)
        if (g_width[i] > maxlen)
            maxlen = g_width[i];

    printf(" ");
    for (i = 0; i < maxlen + 2; i++)
        printf("_");
    printf("\n");
    for (i = 0; i < g_nlines; i++) {
        const char *lc = (i == 0) ? "/" : ((i == g_nlines - 1) ? "\\" : "|");
        const char *rc = (i == 0) ? "\\" : ((i == g_nlines - 1) ? "/" : "|");
        int k;
        printf("%s %s", lc, g_lines[i]);
        for (k = g_width[i]; k < maxlen; k++)
            printf(" ");
        printf(" %s\n", rc);
    }
    printf(" ");
    for (i = 0; i < maxlen + 2; i++)
        printf("-");
    printf("\n");
}

int main(int argc, char **argv) {
    static char msg[8192];
    size_t mlen = 0;
    int width = DEF_WIDTH;
    const char *file = NULL;
    int i;

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-w") == 0 && i + 1 < argc) {
            width = atoi(argv[++i]);
        } else if (strcmp(argv[i], "-f") == 0 && i + 1 < argc) {
            file = argv[++i];
        } else {
            size_t l = strlen(argv[i]);
            if (mlen && mlen < sizeof msg - 1)
                msg[mlen++] = ' ';
            if (mlen + l >= sizeof msg)
                l = sizeof msg - 1 - mlen;
            memcpy(msg + mlen, argv[i], l);
            mlen += l;
        }
    }
    msg[mlen] = 0;

    if (file) {
        FILE *f = fopen(file, "r");
        if (!f) {
            printf("cowsay: %s: cannot open\n", file);
            return 1;
        }
        mlen = 0;
        while (mlen < sizeof msg - 1 && fgets(msg + mlen, (int)(sizeof msg - mlen), f))
            mlen = strlen(msg);
        fclose(f);
        while (mlen && (msg[mlen - 1] == '\n' || msg[mlen - 1] == '\r' ||
                        msg[mlen - 1] == ' ' || msg[mlen - 1] == '\t'))
            msg[--mlen] = 0;
    } else if (mlen == 0) {
        if (fgets(msg, sizeof msg, stdin)) {
            mlen = strlen(msg);
            while (mlen && (msg[mlen - 1] == '\n' || msg[mlen - 1] == '\r'))
                msg[--mlen] = 0;
        }
    }
    if (mlen == 0) {
        printf("cowsay: no message (usage: cowsay [-w N] [-f FILE] [message...])\n");
        return 2;
    }

    wrap(msg, width);
    bubble();
    for (i = 0; COW[i]; i++)
        printf("%s\n", COW[i]);
    return 0;
}
