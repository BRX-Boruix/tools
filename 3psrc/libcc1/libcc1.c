/* libcc1.c —— 3P6-2 第二波（C1 批）的**系统内**运行时验收。
 *
 * 用法（在 BORUIX 内，由 tcc 编译后运行）：
 *     tcc libcc1.c -o /volumes/BORUIX_DATA/3p/libcc1 && /volumes/BORUIX_DATA/3p/libcc1
 *
 * 为什么要有它：反向对账（llvm-nm 读 libc.a）只能证明**符号存在**与**头文件声明**，
 * 证明不了「行为对」。本程序在系统内真跑一遍每个 C1 项，逐条打印 ok/FAIL，
 * 最后给出 fails 计数与 atexit/on_exit 的 LIFO 证据。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <fnmatch.h>
#include <glob.h>
#include <regex.h>
#include <setjmp.h>
#include <time.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/stat.h>  /* struct stat 是**完整类型**才能定义对象（tcc 实测：只声明会报
                        * "initialization of incomplete type"） */

static int fails = 0;
static int seq = 0;
static int onexit_ok = 0;

static void chk(int cond, const char *what) {
    if (cond) {
        printf("ok   %s\n", what);
    } else {
        printf("FAIL %s\n", what);
        fails++;
    }
}

static void h_atexit(void) {
    seq++;
    printf("ok   atexit handler ran (seq=%d)\n", seq);
}

static void h_onexit(int status, void *arg) {
    seq++;
    printf("ok   on_exit handler ran (seq=%d status=%d arg=%s)\n",
           seq, status, (const char *)arg);
    /* 最后跑的那个处理器做总判定：POSIX 要求 atexit 与 on_exit 在**同一个 LIFO 栈**里，
     * 故先登记的 on_exit 应当**最后**跑（seq==2）。 */
    if (seq == 2 && status == 0 && strcmp((const char *)arg, "onexit-arg") == 0)
        onexit_ok = 1;
    if (onexit_ok)
        printf("PASS libcc1 LIFO: on_exit 与 atexit 共用一个栈且按登记顺序逆序\n");
    else
        printf("FAIL libcc1 LIFO: on_exit/atexit 顺序或参数不对\n");
}

int main(void) {
    printf("=== libcc1: C1 批 libc 面系统内验收 ===\n");

    /* ---- memalign / valloc ---- */
    {
        void *p = memalign(64, 128);
        chk(p != NULL && ((unsigned long)p % 64UL) == 0, "memalign 64 对齐");
        free(p);
        long ps = getpagesize();
        void *q = valloc(64);
        chk(q != NULL && ps > 0 && ((unsigned long)q % (unsigned long)ps) == 0,
            "valloc 页对齐（页大小取自内核，不硬编码）");
        free(q);
    }

    /* ---- strptime ---- */
    {
        struct tm t;
        memset(&t, 0, sizeof t);
        char *e = strptime("2026-10-07 13:45:59", "%Y-%m-%d %H:%M:%S", &t);
        chk(e != NULL && *e == '\0', "strptime 消耗整串");
        chk(t.tm_year == 126 && t.tm_mon == 9 && t.tm_mday == 7,
            "strptime 日期（tm_year=年-1900、tm_mon 0 起）");
        chk(t.tm_hour == 13 && t.tm_min == 45 && t.tm_sec == 59, "strptime 时间");
        struct tm t2;
        memset(&t2, 0, sizeof t2);
        chk(strptime("07 Oct 2026", "%d %b %Y", &t2) != NULL && t2.tm_mon == 9,
            "strptime %b 月份缩写");
        chk(strptime("nope", "%Y", &t2) == NULL, "strptime 失败如实返回 NULL");
    }

    /* ---- fnmatch ---- */
    chk(fnmatch("*.c", "foo.c", 0) == 0, "fnmatch *.c foo.c");
    chk(fnmatch("*.c", "foo.h", 0) == FNM_NOMATCH, "fnmatch *.c foo.h");
    chk(fnmatch("a?c", "abc", 0) == 0, "fnmatch a?c");
    chk(fnmatch("[a-c]x", "bx", 0) == 0, "fnmatch [a-c]x");
    chk(fnmatch("[!a-c]x", "dx", 0) == 0, "fnmatch [!a-c]x");
    chk(fnmatch("a*c", "a/b/c", FNM_PATHNAME) == FNM_NOMATCH, "fnmatch FNM_PATHNAME 不跨 /");
    chk(fnmatch("*", ".hidden", FNM_PERIOD) == FNM_NOMATCH, "fnmatch FNM_PERIOD 不匹配开头点");

    /* ---- getopt / getopt_long ---- */
    {
        char *av[] = { (char *)"prog", (char *)"-a", (char *)"-bval", NULL };
        optind = 1;
        chk(getopt(3, av, "ab:") == 'a', "getopt -a");
        int c2 = getopt(3, av, "ab:");
        chk(c2 == 'b' && optarg != NULL && strcmp(optarg, "val") == 0, "getopt -bval 带参数");
        chk(getopt(3, av, "ab:") == -1, "getopt 到末尾返回 -1");

        static struct option lo[] = {
            { "verbose", no_argument, NULL, 'v' },
            { "out", required_argument, NULL, 'o' },
            { NULL, 0, NULL, 0 },
        };
        char *av2[] = { (char *)"prog", (char *)"--verbose", (char *)"--out=file", NULL };
        optind = 1;
        chk(getopt_long(3, av2, "", lo, NULL) == 'v', "getopt_long --verbose");
        int l2 = getopt_long(3, av2, "", lo, NULL);
        chk(l2 == 'o' && optarg != NULL && strcmp(optarg, "file") == 0,
            "getopt_long --out=file（内联值）");
    }

    /* ---- fnmatch 之上的 glob ---- */
    {
        glob_t g;
        memset(&g, 0, sizeof g);
        int gr = glob("/programs/*.elf", 0, NULL, &g);
        chk(gr == 0 && g.gl_pathc >= 1, "glob /programs/*.elf 至少匹配一个");
        if (gr == 0) {
            printf("     glob 匹配 %u 项，首项=%s\n", (unsigned)g.gl_pathc, g.gl_pathv[0]);
            globfree(&g);
        }
        memset(&g, 0, sizeof g);
        chk(glob("/programs/definitely-no-such-*.elf", 0, NULL, &g) == GLOB_NOMATCH,
            "glob 无匹配返回 GLOB_NOMATCH");
    }

    /* ---- 正则 ---- */
    {
        regex_t re;
        regmatch_t m[3];
        int rc = regcomp(&re, "(a+)(b*)c", REG_EXTENDED);
        chk(rc == 0, "regcomp ERE");
        if (rc == 0) {
            rc = regexec(&re, "xxaaabbczz", 3, m, 0);
            chk(rc == 0, "regexec 命中");
            if (rc == 0) {
                chk(m[0].rm_so == 2 && m[0].rm_eo == 8, "整体匹配偏移 2..8");
                chk(m[1].rm_so == 2 && m[1].rm_eo == 5, "第 1 组偏移 2..5（a+ 贪婪）");
                chk(m[2].rm_so == 5 && m[2].rm_eo == 7, "第 2 组偏移 5..7（b*）");
            }
            chk(regexec(&re, "zzz", 0, NULL, 0) == REG_NOMATCH, "regexec 不命中");
            char eb[64];
            size_t need = regerror(REG_BADBR, &re, eb, sizeof eb);
            chk(need > 1 && strlen(eb) > 0, "regerror 有文案");
            regfree(&re);
        }
        regex_t re2;
        chk(regcomp(&re2, "a{1,3}", REG_EXTENDED) == 0, "regcomp 区间量词");
        chk(regexec(&re2, "aaa", 0, NULL, 0) == 0, "regexec a{1,3} 匹配 aaa");
        regfree(&re2);
        regex_t re3;
        chk(regcomp(&re3, "[[:alpha:]]", REG_EXTENDED) == REG_ECTYPE,
            "regcomp [[:alpha:]] 如实报 REG_ECTYPE（本系统无 locale 表）");
    }

    /* ---- sigsetjmp / siglongjmp ---- */
    {
        static sigjmp_buf jb;
        volatile int flag = 0;
        if (sigsetjmp(jb, 1) == 0) {
            flag = 1;
            siglongjmp(jb, 42);
            printf("FAIL siglongjmp 竟然返回了\n");
            fails++;
        } else {
            chk(flag == 1, "sigsetjmp/siglongjmp 往返（跳转前写入的 flag 可见）");
        }
    }

    /* ---- tmpfile（依赖内核 O_EXCL + FmMode::ReadWrite） ---- */
    {
        FILE *tf = tmpfile();
        chk(tf != NULL, "tmpfile 创建成功");
        if (tf != NULL) {
            const char *msg = "hello-tmpfile";
            size_t n = fwrite(msg, 1, strlen(msg), tf);
            chk(n == strlen(msg), "tmpfile 可写（fwrite 全量）");
            long pos0 = ftell(tf);
            chk(fseek(tf, 0, SEEK_SET) == 0, "tmpfile fseek 回起点");
            long pos1 = ftell(tf);
            char rb[32];
            memset(rb, 0, sizeof rb);
            size_t r = fread(rb, 1, strlen(msg), tf);
            int fr_errno = errno;
            long pos2 = ftell(tf);
            printf("     tmpfile 诊断: fwrite=%u ftell(w 后)=%ld ftell(seek 后)=%ld "
                   "fread=%u ftell(读后)=%ld eof=%d err=%d errno=%d rb=[%s]\n",
                   (unsigned)n, pos0, pos1, (unsigned)r, pos2,
                   feof(tf), ferror(tf), fr_errno, rb);
            chk(r == strlen(msg) && strcmp(rb, msg) == 0,
                "tmpfile 可读（读回与写入一致 ⇒ FmMode::ReadWrite 真的双向）");
            chk(fclose(tf) == 0, "tmpfile fclose");
        }
    }

    /* ---- 对照实验：同一「写 → fseek(0) → 读回」序列在**普通文件**上 ----
     * 用途：把「定位读本身有问题」与「unlink 之后写入不可见」两种假设分开。
     * 结论（实测）：普通文件**能**读回；故根因是后者，tmpfile 因此改为延迟删除。 */
    {
        // **先删干净**：/scratch 在带系统盘启动时跨重启持久（内核 vfs_init 成文），
        // 上一次运行残留的旧文件会让「截断 + 写入」的观测被历史字节污染。
        unlink("/scratch/c1probe.txt");
        FILE *nf = fopen("/scratch/c1probe.txt", "w+");
        chk(nf != NULL, "fopen w+ 普通文件");
        if (nf != NULL) {
            const char *m2 = "hello-normal";
            size_t w2 = fwrite(m2, 1, strlen(m2), nf);
            int s2 = fseek(nf, 0, SEEK_SET);
            char rb2[32];
            memset(rb2, 0, sizeof rb2);
            size_t r2 = fread(rb2, 1, strlen(m2), nf);
            struct stat stb;
            memset(&stb, 0, sizeof stb);
            int fsr = fstat(fileno(nf), &stb);
            printf("     对照(普通文件): fwrite=%u fseek=%d fread=%u fstat=%d size=%ld rb=[%s]\n",
                   (unsigned)w2, s2, (unsigned)r2, fsr, (long)stb.st_size, rb2);
            chk(r2 == strlen(m2) && strcmp(rb2, m2) == 0, "普通文件 fseek+fread 定位读回");
            fclose(nf);
            unlink("/scratch/c1probe.txt");
        }
    }

    /* ---- on_exit / atexit（顺序证据在处理器里打印） ---- */
    chk(on_exit(h_onexit, (void *)"onexit-arg") == 0, "on_exit 登记成功");
    chk(atexit(h_atexit) == 0, "atexit 登记成功");

    printf("libcc1 checks: fails=%d\n", fails);
    /* 显式 exit 而不是 return：确保退出处理器一定被执行（不依赖 crt 的返回路径）。 */
    exit(0);
}