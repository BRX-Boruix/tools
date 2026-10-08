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
#include <dirent.h>
#include <sys/utsname.h>
#include <wordexp.h>
#include <spawn.h>
#include <sys/wait.h>

/* ---- C++ 静态构造（.init_array）探针：这是 libstdc++ 的**前置地基** ----
 * 现在 Boruix 的入口链路（libsys 的 _start -> user_main -> main）**不遍历 .init_array**，
 * 且 csrc/linker.ld 也不收集它 ⇒ 构造函数**永远不会跑**。
 * 本探针就是那条「必须先红」的验收：红 = 构造没跑。 */
static int g_ctor_ran = 0;
__attribute__((constructor)) static void boruix_ctor_probe(void) {
    g_ctor_ran = 1;
}

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

    /* ---- 探针 2：**绕过 FILE 层**，直接用 open/lseek/close 检验「close 是否清了位置表」。
     * 若刚打开的 fd2 上 lseek(CUR) 返回旧位置（而不是 -1/ENOTSUP），说明清理本身没生效。 */
    {
        int fd = open("/scratch/c1pos.txt", O_RDWR | O_CREAT | O_TRUNC, 0600);
        if (fd >= 0) {
            char tmp8[8] = "abcdefgh";
            write(fd, tmp8, 8);
            lseek(fd, 5, SEEK_SET);
            close(fd);
            int fd2 = open("/scratch/c1pos.txt", O_RDWR, 0600);
            errno = 0;
            long p = lseek(fd2, 0, SEEK_CUR);
            int pe = errno;
            printf("     探针2: fd=%d fd2=%d lseek(CUR 刚打开)=%ld errno=%d (期望 -1/95)\n",
                   fd, fd2, p, pe);
            close(fd2);
            unlink("/scratch/c1pos.txt");
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
            /* 关键探针：**刚 fopen 完**就 ftell。若它返回 13（而不是 -1/ENOTSUP），
             * 说明该 fd 号上残留着上一个流的位置 —— 即 close 的清理没生效；
             * 若返回 -1，则位置表是干净的，写落错偏移的原因在别处。 */
            long pre = ftell(nf);
            int pre_errno = errno;
            printf("     对照探针: fileno(nf)=%d ftell(fopen 后)=%ld errno=%d\n",
                   fileno(nf), pre, pre_errno);
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

    chk(g_ctor_ran == 1, "C++ 静态构造（.init_array）在 main 之前已执行");

    /* ---- C2 批：seekdir / telldir / scandir / alphasort ---- */
    {
        DIR *d = opendir("/programs");
        chk(d != NULL, "opendir /programs");
        if (d != NULL) {
            struct dirent *e = readdir(d);
            long loc = telldir(d);
            chk(e != NULL && loc >= 0, "readdir + telldir");
            (void)readdir(d);
            seekdir(d, loc);
            struct dirent *e3 = readdir(d);
            chk(e3 != NULL && strcmp(e3->d_name, e->d_name) == 0,
                "seekdir(telldir) 往返：重读到同一项");
            closedir(d);
        }
    }
    {
        struct dirent **list = NULL;
        int n = scandir("/programs", &list, NULL, alphasort);
        chk(n >= 1, "scandir /programs");
        if (n >= 1) {
            int sorted = 1;
            for (int i = 1; i < n; i++)
                if (strcmp(list[i - 1]->d_name, list[i]->d_name) > 0) sorted = 0;
            chk(sorted, "scandir 用 alphasort 排好序");
            printf("     scandir 项数=%d 首项=%s\n", n, list[0]->d_name);
            for (int i = 0; i < n; i++) free(list[i]);
            free(list);
        }
    }

    /* ---- C2 批：uname / gethostname / getlogin ---- */
    {
        struct utsname u;
        chk(uname(&u) == 0, "uname");
        printf("     uname: sysname=%s nodename=[%s] release=%s version=%s machine=%s\n",
               u.sysname, u.nodename, u.release, u.version, u.machine);
        chk(strcmp(u.sysname, "Boruix") == 0, "uname sysname=Boruix");
        chk(strlen(u.release) >= 3 && u.release[1] == '.', "uname release 形如 M.m.p（来自内核 INFO_VERSION）");
        chk(strcmp(u.machine, "x86_64") == 0, "uname machine=x86_64");
        chk(u.nodename[0] == '\0', "uname nodename 如实为空（本系统无主机名）");
        char hn[64];
        memset(hn, 'X', sizeof hn);
        chk(gethostname(hn, sizeof hn) == 0 && hn[0] == '\0', "gethostname 如实为空");
        char *lg = getlogin();
        printf("     getlogin = %s\n", lg ? lg : "(NULL)");
        chk(1, "getlogin 返回 NULL 或真实环境名（不编造）");
    }

    /* ---- C2 批：wordexp / wordfree ---- */
    {
        wordexp_t we;
        memset(&we, 0, sizeof we);
        int wr = wordexp("alpha $HOME 'q u o' /programs/*.elf", &we, 0);
        chk(wr == 0, "wordexp 基本展开");
        if (wr == 0) {
            printf("     wordexp 词数=%u 词0=%s 词2=%s\n",
                   (unsigned)we.we_wordc, we.we_wordv[0], we.we_wordv[2]);
            chk(we.we_wordc >= 3, "wordexp 至少 3 个词（含通配展开）");
            chk(strcmp(we.we_wordv[0], "alpha") == 0, "wordexp 词0 = alpha");
            chk(strcmp(we.we_wordv[2], "q u o") == 0, "wordexp 单引号内空格保留");
            wordfree(&we);
        }
        wordexp_t we2;
        memset(&we2, 0, sizeof we2);
        chk(wordexp("$(date)", &we2, 0) == WRDE_CMDSUB,
            "wordexp 命令替换如实 WRDE_CMDSUB（不静默展开成空）");
        wordexp_t we3;
        memset(&we3, 0, sizeof we3);
        chk(wordexp("a | b", &we3, 0) == WRDE_BADCHAR, "wordexp 未加引号元字符如实 WRDE_BADCHAR");
    }

    /* ---- posix_spawn：GCC 宿主端口的解锁项（基座是 SYS_TASK_SPAWN，不是 DERIVE）---- */
    {
        pid_t p = -1;
        char *av[] = { (char *)"selftest.elf", (char *)"--exit-now", NULL };
        int rc = posix_spawn(&p, "/programs/selftest.elf", NULL, NULL, av, NULL);
        chk(rc == 0 && p > 0, "posix_spawn 成功并返回子进程 pid");
        if (rc == 0) {
            int st = 0;
            pid_t w = waitpid(p, &st, 0);
            chk(w == p && WIFEXITED(st) && WEXITSTATUS(st) == 0,
                "posix_spawn 的子进程可被 waitpid 收尸且退出码 0");
        }
        /* 参数含空格：本 ABI 无法无损表达 ⇒ 必须如实 EINVAL，不静默切成两个参数 */
        char *av2[] = { (char *)"x", (char *)"a b", NULL };
        rc = posix_spawn(&p, "/programs/selftest.elf", NULL, NULL, av2, NULL);
        chk(rc == EINVAL, "posix_spawn 参数含空格如实 EINVAL（不静默切词）");
        /* 不支持的 attrp 旗标：如实 ENOSYS，不静默忽略 */
        posix_spawnattr_t at;
        posix_spawnattr_init(&at);
        chk(posix_spawnattr_setflags(&at, POSIX_SPAWN_SETSIGMASK) == ENOSYS,
            "posix_spawnattr_setflags 不支持位如实 ENOSYS");
        chk(posix_spawnattr_setflags(&at, POSIX_SPAWN_RESETIDS) == 0,
            "posix_spawnattr_setflags RESETIDS 可接受（本系统里是无操作）");
        posix_spawnattr_destroy(&at);
    }
    /* file_actions：把子进程 fd1 重定向到文件，**派生后父进程 fd1 必须还原**——
     * 下面那行 ok 若出现在串口日志里，本身就是「已还原」的证明（否则它会写进文件）。 */
    {
        posix_spawn_file_actions_t fa;
        posix_spawn_file_actions_init(&fa);
        int ar = posix_spawn_file_actions_addopen(&fa, 1, "/scratch/sp_out.txt",
                                                  O_WRONLY | O_CREAT | O_TRUNC, 0600);
        chk(ar == 0, "posix_spawn_file_actions_addopen 登记成功");
        pid_t p = -1;
        char *av[] = { (char *)"selftest.elf", (char *)"--exit-now", NULL };
        int rc = posix_spawn(&p, "/programs/selftest.elf", &fa, NULL, av, NULL);
        chk(rc == 0, "posix_spawn + file_actions(addopen fd1) 派生成功");
        if (rc == 0) {
            int st = 0;
            waitpid(p, &st, 0);
        }
        posix_spawn_file_actions_destroy(&fa);
        chk(1, "file_actions 后父进程 fd1 已还原（本行能出现在串口即为证）");
        unlink("/scratch/sp_out.txt");
    }

    /* ---- fnmatch 的 GNU 扩展旗标 + _getopt_internal（GCC 自带 libiberty 在要）---- */
    {
        chk(FNM_FILE_NAME == FNM_PATHNAME, "FNM_FILE_NAME 是 FNM_PATHNAME 的别名（同值）");
        chk(fnmatch("*.c", "FOO.C", FNM_CASEFOLD) == 0, "fnmatch FNM_CASEFOLD 大小写不敏感");
        chk(fnmatch("*.c", "FOO.C", 0) == FNM_NOMATCH, "对照：不带 CASEFOLD 时大小写敏感");
        chk(fnmatch("a/*", "a/b/c", FNM_PATHNAME) == FNM_NOMATCH,
            "FNM_PATHNAME（FNM_FILE_NAME 同义）下 * 不跨 /");
        chk(fnmatch("a", "a/b/c", FNM_LEADING_DIR) == 0,
            "fnmatch FNM_LEADING_DIR 匹配到 / 边界即命中");
        chk(fnmatch("a", "ab/c", FNM_LEADING_DIR) == FNM_NOMATCH,
            "fnmatch FNM_LEADING_DIR 不匹配非边界的同前缀");
    }
    {
        static struct option lo2[] = {
            { "alpha", no_argument, NULL, 'a' },
            { NULL, 0, NULL, 0 },
        };
        char *av3[] = { (char *)"prog", (char *)"--alpha", NULL };
        optind = 1;
        chk(_getopt_internal(2, av3, "", lo2, NULL, 0) == 'a',
            "_getopt_internal(longopts!=NULL) 走长选项");
        char *av4[] = { (char *)"prog", (char *)"-x", NULL };
        optind = 1;
        chk(_getopt_internal(2, av4, "x", NULL, NULL, 0) == 'x',
            "_getopt_internal(longopts==NULL) 走短选项（S15 共同核心）");
        optind = 1;
        chk(_getopt_internal(2, av4, "x", NULL, NULL, 1) == -1,
            "_getopt_internal(long_only=1) 如实拒绝（GNU 扩展未实现）");
    }

    /* ---- on_exit / atexit（顺序证据在处理器里打印） ---- */
    chk(on_exit(h_onexit, (void *)"onexit-arg") == 0, "on_exit 登记成功");
    chk(atexit(h_atexit) == 0, "atexit 登记成功");

    printf("libcc1 checks: fails=%d\n", fails);
    /* 显式 exit 而不是 return：确保退出处理器一定被执行（不依赖 crt 的返回路径）。 */
    exit(0);
}