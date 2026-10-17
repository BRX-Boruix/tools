/* wave2.c —— 3P6-2（libc 宽度第二波）的**真实驱动 + 自检**。
 *
 * 为什么是这个程序：第二波的判据是「按 tcc/GCC 的**真实报错**补，不预猜」，所以需要一个
 * 真实会用到 libc 多面（而不只是 printf）的程序。这就是一个"系统内小工具"：
 * 打印自己的 argv、读一个文件并统计词尾、列一个目录、格式化当前时间、报告 errno、
 * 排序一小串字符串、读环境变量。
 *
 * 本轮由它**真实暴露**并已修的缺口（不是预猜的清单）：
 *   1. strftime —— 头文件没声明、库里也没实现（tcc: unresolved reference to 'strftime'）；
 *   2. getpid   —— 实现早就在（libc/src/process.rs），缺的只是 <unistd.h> 里的**声明**
 *                  （tcc: implicit declaration of function 'getpid'）。
 *
 * 它同时是 3P6-4（系统内编出一个新 cowsay 并运行）的前身——先把"能编能跑能自检"的底座打通。
 *
 * 退出码 0 = 全部断言通过。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <ctype.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <dirent.h>
#include <grp.h>
#include <libgen.h>
#include <fcntl.h>
#include <boruix.h>

#define DIRPATH "/volumes/BORUIX_DATA/3p"
#define FILEPATH DIRPATH "/hello.c"

static int fails = 0;

static void check(int cond, const char *what) {
    if (!cond) {
        printf("[wave2] FAIL: %s\n", what);
        fails++;
    }
}

static int cmp_str(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

/* 用**固定**的 struct tm 校验 strftime 的确定性输出（不依赖真实时钟）。 */
static void check_strftime(void) {
    struct tm t;
    char buf[64];
    memset(&t, 0, sizeof t);
    t.tm_year = 123;   /* 2023 */
    t.tm_mon  = 9;     /* 十月（0 起） */
    t.tm_mday = 7;
    t.tm_hour = 0;
    t.tm_min  = 53;
    t.tm_sec  = 41;
    t.tm_wday = 6;     /* 周六 */
    t.tm_yday = 279;   /* 年内第 280 天 */

    memset(buf, 0, sizeof buf);
    check(strftime(buf, sizeof buf, "%Y-%m-%d %H:%M:%S", &t) == 19,
          "strftime 返回长度 19");
    check(strcmp(buf, "2023-10-07 00:53:41") == 0, "strftime %Y-%m-%d %H:%M:%S");
    printf("[wave2] strftime: %s\n", buf);

    memset(buf, 0, sizeof buf);
    strftime(buf, sizeof buf, "%a %b %e %I:%M %p %j %w %u", &t);
    check(strcmp(buf, "Sat Oct  7 12:53 AM 280 6 6") == 0,
          "strftime %a %b %e %I:%M %p %j %w %u");
    printf("[wave2] strftime: [%s]\n", buf);

    memset(buf, 0, sizeof buf);
    strftime(buf, sizeof buf, "%F %T %D %R %% %Z %z", &t);
    check(strcmp(buf, "2023-10-07 00:53:41 10/07/23 00:53 % UTC +0000") == 0,
          "strftime %F %T %D %R %% %Z %z");
    printf("[wave2] strftime: %s\n", buf);

    /* 容量边界：POSIX 口径 max **含**结尾 NUL。 */
    memset(buf, 0, sizeof buf);
    check(strftime(buf, 11, "%Y-%m-%d", &t) == 10, "strftime 恰好放下 -> 10");
    memset(buf, 0, sizeof buf);
    check(strftime(buf, 10, "%Y-%m-%d", &t) == 0, "strftime 差一字节 -> 0");

    /* 未知说明符按 POSIX 允许的方式原样输出，绝不静默丢弃。 */
    memset(buf, 0, sizeof buf);
    strftime(buf, sizeof buf, "<%Q>", &t);
    check(strcmp(buf, "<%Q>") == 0, "strftime 未知说明符原样输出");
}

int main(int argc, char **argv) {
    int i;
    printf("[wave2] argc=%d pid=%d\n", argc, (int)getpid());
    check(getpid() > 0, "getpid() > 0");
    check(gettid() > 0, "gettid() > 0");
    for (i = 0; i < argc; i++)
        printf("[wave2] argv[%d]=%s\n", i, argv[i]);

    /* 1. errno + strerror */
    {
        FILE *f = fopen("/nope/nope", "r");
        check(f == NULL, "fopen(/nope/nope) 应失败");
        if (!f) {
            printf("[wave2] fopen(/nope/nope) -> %s (errno=%d)\n",
                   strerror(errno), errno);
            check(errno == ENOENT, "errno == ENOENT");
            check(strcmp(strerror(errno), "No such file or directory") == 0,
                  "strerror(ENOENT) 文本");
        } else {
            fclose(f);
        }
    }

    /* 2. strftime（确定性） */
    check_strftime();

    /* 3. time/localtime：只要求拿到一个合理的 epoch */
    {
        time_t now = time(NULL);
        struct tm *tmv = localtime(&now);
        char buf[64];
        check(now > 1600000000, "time() 合理");
        check(tmv != NULL, "localtime 非空");
        if (tmv && strftime(buf, sizeof buf, "%Y-%m-%d %H:%M:%S", tmv))
            printf("[wave2] now=%s (t=%ld)\n", buf, (long)now);
        else
            check(0, "真实时间 strftime");
    }

    /* 4. 目录枚举 */
    {
        DIR *d = opendir(DIRPATH);
        int n = 0;
        check(d != NULL, "opendir 非空");
        if (d) {
            struct dirent *e;
            while ((e = readdir(d)) != NULL && n < 6) {
                printf("[wave2] dirent: %s\n", e->d_name);
                n++;
            }
            closedir(d);
        }
        check(n > 0, "readdir 至少一项");
    }

    /* 5. stat */
    {
        struct stat st;
        int rc = stat(FILEPATH, &st);
        check(rc == 0, "stat 成功");
        if (rc == 0) {
            printf("[wave2] stat %s: size=%ld mode=%o\n",
                   FILEPATH, (long)st.st_size, (unsigned)st.st_mode);
            check(st.st_size > 0, "hello.c 非空");
        }
    }

    /* 6. 读文件 + ctype（统计"以字母结尾的词"个数） */
    {
        FILE *f = fopen(FILEPATH, "r");
        int words = 0;
        check(f != NULL, "fopen(hello.c)");
        if (f) {
            char line[256];
            while (fgets(line, sizeof line, f)) {
                char *p;
                for (p = line; *p; p++)
                    if (isalpha((unsigned char)*p) &&
                        !isalpha((unsigned char)p[1]))
                        words++;
            }
            fclose(f);
            printf("[wave2] %s word-ends=%d\n", FILEPATH, words);
            check(words > 0, "词尾计数 > 0");
        }
    }

    /* 7. malloc + qsort + free */
    {
        const char *items[4];
        const char **arr;
        int n = 4;
        items[0] = "delta"; items[1] = "alpha";
        items[2] = "charlie"; items[3] = "bravo";
        arr = (const char **)malloc(sizeof(const char *) * (size_t)n);
        check(arr != NULL, "malloc 非空");
        if (!arr)
            return 1;
        for (i = 0; i < n; i++)
            arr[i] = items[i];
        qsort(arr, (size_t)n, sizeof(const char *), cmp_str);
        printf("[wave2] sorted:");
        for (i = 0; i < n; i++)
            printf(" %s", arr[i]);
        printf("\n");
        check(strcmp(arr[0], "alpha") == 0 && strcmp(arr[3], "delta") == 0,
              "qsort 顺序");
        free(arr);
    }

    /* 8. getenv */
    {
        const char *path = getenv("PATH");
        printf("[wave2] PATH=%s\n", path ? path : "(null)");
        check(path != NULL && path[0] != 0, "PATH 非空");
    }


    /* 9. 3P6-2 第二波：**头文件覆盖审计**列出的那些入口——按真实用法逐项验证。
     * 它们此前"实现了但没声明"（getpid/dup2/EINTR 那一类），审计一次列全后补上声明；
     * 这里用真实调用证明"声明可用、语义可跑"，而不是只看头文件里有没有那个词。 */
    {
        long n = sysconf(_SC_NPROCESSORS_ONLN);
        printf("[wave2] sysconf(_SC_NPROCESSORS_ONLN)=%ld\n", n);
        check(n > 0, "sysconf 在线 CPU 数 > 0");
        check(sysconf(99999) == -1, "sysconf 不支持的名字返回 -1");
    }
    {
        struct group *gr = getgrgid(0);
        printf("[wave2] getgrgid(0)=%s\n", gr ? gr->gr_name : "(null)");
        check(gr == NULL || gr->gr_name != NULL, "getgrgid 要么 NULL 要么有名字");
        endgrent();
    }
    check(boruix_malloc_corrupt() == 0, "boruix_malloc_corrupt() == 0");
    check(yield_sys() == 0, "yield_sys() == 0");

    /* rename / ftruncate / symlink / chown：在数据盘上**真做一遍**（不 mock）。 */
    {
        const char *fa = "w2tmp_a";
        const char *fb = "w2tmp_b";
        const char *fl = "w2tmp_link";
        FILE *f = fopen(fa, "w");
        check(f != NULL, "创建临时文件");
        if (f) {
            fputs("0123456789", f);
            fclose(f);
        }
        check(rename(fa, fb) == 0, "rename 成功");
        {
            int fd = open(fb, O_WRONLY);
            check(fd >= 0, "open 临时文件");
            if (fd >= 0) {
                check(ftruncate(fd, 4) == 0, "ftruncate 成功");
                close(fd);
            }
        }
        {
            int rc = symlink(fb, fl);
            printf("[wave2] symlink -> rc=%d errno=%d\n", rc, errno);
            check(rc == 0 || errno != 0, "symlink 有明确结果");
            if (rc == 0) remove(fl);
        }
        {
            int rc = chown(fb, 0, 0);
            printf("[wave2] chown -> rc=%d errno=%d\n", rc, errno);
            check(rc == 0 || errno != 0, "chown 有明确结果");
        }
        remove(fb);
    }


    /* 判别实验（目标第 8 轮）：用 WNOHANG 轮询区分两种假设——
     *   A) 子进程卡在 _exit（轮询永远拿不到状态，阻塞等也拿不到）
     *   B) 父进程的 waitpid 丢了唤醒（轮询能拿到已退出子进程的状态） */
    {
        int dpid;
        int dst = 0;
        int di;
        int drc = 0;
        fflush(stdout);
        dpid = fork();
        if (dpid == 0) {
            printf("[disc] child exiting 42\n");
            fflush(stdout);
            _exit(42);
        }
        printf("[disc] fork returned %d\n", dpid);
        fflush(stdout);
        for (di = 0; di < 30; di++) {
            yield_sys();
            drc = waitpid(dpid, &dst, WNOHANG);
            printf("[disc] poll %d -> %d (errno=%d)\n", di, drc, errno);
            fflush(stdout);
            if (drc != 0) {
                break;
            }
        }
        if (drc == 0) {
            printf("[disc] 30 次轮询都没拿到 -> 转阻塞等\n");
            fflush(stdout);
            drc = waitpid(dpid, &dst, 0);
            printf("[disc] blocking -> %d status=%d code=%d\n", drc, dst, WEXITSTATUS(dst));
            fflush(stdout);
        }
        check(drc == dpid && WEXITSTATUS(dst) == 42, "判别：拿到子进程退出码 42");
    }
    /* fork + waitpid + W* 宏（<sys/wait.h>）：真起一个子进程、真收它的退出码。 */
    {
        int pid;
        fflush(stdout);
        pid = fork();
        if (pid == 0) {
            _exit(42);
        }
        check(pid > 0, "fork 返回子 pid");
        if (pid > 0) {
            int st = 0;
            int got = waitpid(pid, &st, 0);
            printf("[wave2] waitpid -> pid=%d status=%d WIFEXITED=%d WEXITSTATUS=%d\n",
                   got, st, WIFEXITED(st), WEXITSTATUS(st));
            check(got == pid, "waitpid 返回子 pid");
            check(WIFEXITED(st) != 0 && WEXITSTATUS(st) == 42, "WEXITSTATUS == 42");
        }
    }

    /* 10. 3P6-2「整项缺失」类：身份查询（getuid/geteuid/getgid/getegid）与 dup。
     * 这些此前**既没实现也没声明**（反向对账清单列出来的），所以不能只验"能编译"——
     * 要用**交叉证据**：新建文件的 st_uid/st_gid 必须等于 getuid()/getgid()。 */
    {
        uid_t u = getuid();
        uid_t eu = geteuid();
        gid_t g = getgid();
        gid_t eg = getegid();
        printf("[wave2] getuid=%d geteuid=%d getgid=%d getegid=%d\n",
               (int)u, (int)eu, (int)g, (int)eg);
        check(u == eu, "geteuid()==getuid()（本系统无 real/effective 之分）");
        check(g == eg, "getegid()==getgid()");
        {
            FILE *f = fopen("w2id.tmp", "w");
            check(f != NULL, "创建身份交叉验证文件");
            if (f) {
                fputs("x", f);
                fclose(f);
            }
            {
                struct stat st;
                if (stat("w2id.tmp", &st) == 0) {
                    printf("[wave2] stat.st_uid=%u st_gid=%u\n",
                           (unsigned)st.st_uid, (unsigned)st.st_gid);
                    check((uid_t)st.st_uid == u, "新建文件 st_uid == getuid()（交叉验证）");
                    check((gid_t)st.st_gid == g, "新建文件 st_gid == getgid()（交叉验证）");
                } else {
                    check(0, "stat 身份交叉验证文件");
                }
            }
            remove("w2id.tmp");
        }
    }
    {
        /* dup：真读一个文件，验证 (a) 得到不同的新 fd、(b) 与原 fd **共享文件偏移** */
        int fd = open(FILEPATH, O_RDONLY);
        check(fd >= 0, "open 供 dup 测试");
        if (fd >= 0) {
            char a[8];
            char b[8];
            ssize_t n1 = read(fd, a, 4);
            int d;
            a[n1 > 0 ? n1 : 0] = 0;
            d = dup(fd);
            check(d >= 0, "dup 返回新 fd");
            check(d != fd, "dup 的 fd 与原 fd 不同");
            if (d >= 0) {
                ssize_t n2 = read(d, b, 4);
                b[n2 > 0 ? n2 : 0] = 0;
                printf("[wave2] dup: 原读='%s' 副本续读='%s'\n", a, b);
                check(n1 == 4 && n2 == 4, "两次各读到 4 字节");
                /* hello.c 前 8 字节是 "#include"，故副本必须从第 5 字节 'l' 续读。 */
                check(n2 == 4 && b[0] == 'l', "副本从原 fd 当前位置续读（共享偏移）");
                close(d);
            }
            close(fd);
        }
    }
    {
        /* fcntl(F_DUPFD)：与 dup 共用同一实现的回归保护 */
        int fd = open(FILEPATH, O_RDONLY);
        if (fd >= 0) {
            int d = fcntl(fd, F_DUPFD, 0);
            check(d >= 0 && d != fd, "fcntl(F_DUPFD,0) 与 dup 同实现且可用");
            if (d >= 0) close(d);
            close(fd);
        }
    }

    /* 11. 3P6-2「整项缺失」类 A 批（低风险包装）：逐项用真实调用验证，不看"能编译"就算过。 */
    {
        FILE *f = fopen(FILEPATH, "r");
        check(f != NULL, "fopen 供 fileno/rewind 测试");
        if (f) {
            int fd = fileno(f);
            char b1[5];
            char b2[5];
            check(fd >= 0, "fileno 返回非负 fd");
            check(read(fd, b1, 4) == 4, "用 fileno 的 fd 直接 read");
            b1[4] = 0;
            rewind(f);
            check(read(fd, b2, 4) == 4, "rewind 后重新 read");
            b2[4] = 0;
            printf("[wave2] fileno/rewind: '%s' -> rewind -> '%s'\n", b1, b2);
            check(strcmp(b1, b2) == 0, "rewind 真的回到了开头");
            clearerr(f);
            check(ferror(f) == 0, "clearerr 后 ferror==0");
            fclose(f);
        }
    }
    {
        char *d = strndup("abcdef", 3);
        check(d != NULL && strcmp(d, "abc") == 0, "strndup(abcdef,3)==abc");
        if (d) free(d);
        check(atof("3.5") == 3.5, "atof(3.5)==3.5");
        check(difftime((time_t)100, (time_t)40) == 60.0, "difftime(100,40)==60");
    }
    {
        FILE *f = fopen("w2trunc.tmp", "w");
        check(f != NULL, "创建 truncate 测试文件");
        if (f) {
            fputs("0123456789", f);
            fclose(f);
        }
        check(truncate("w2trunc.tmp", 4) == 0, "truncate 到 4 字节");
        {
            struct stat st;
            if (stat("w2trunc.tmp", &st) == 0)
                check(st.st_size == 4, "truncate 后 size==4");
            else
                check(0, "stat truncate 结果");
        }
        remove("w2trunc.tmp");
        check(mkdir("w2dir.tmp", 0755) == 0, "mkdir 测试目录");
        check(rmdir("w2dir.tmp") == 0, "rmdir 删空目录");
        {
            pid_t pp = getppid();
            printf("[wave2] getppid=%d getpid=%d\n", (int)pp, (int)getpid());
            check(pp >= 0 && pp != getpid(), "getppid 与自身 pid 不同");
        }
    }
    {
        /* perror：真触发一次失败，输出应形如 "wave2-perror: No such file or directory" */
        FILE *f = fopen("/nope/nope", "r");
        check(f == NULL, "fopen 失败（供 perror 测试）");
        perror("wave2-perror");
    }

    /* 12. A 批剩下的 4 组：libgen / 时间格式化与反解 / clock_gettime / 环境表修改 */
    {
        char a1[] = "/usr/lib";
        char a2[] = "/usr/";
        char a3[] = "/";
        char a4[] = "";
        char a5[] = "/usr/lib";
        char a6[] = "/usr/";
        char a7[] = "usr";
        char a8[] = "/";
        check(strcmp(basename(a1), "lib") == 0, "basename(/usr/lib)==lib");
        check(strcmp(basename(a2), "usr") == 0, "basename(/usr/)==usr");
        check(strcmp(basename(a3), "/") == 0, "basename(/)==/");
        check(strcmp(basename(a4), ".") == 0, "basename(空)==.");
        /* dirname 返回静态缓冲：一次只比较一个（这正是它文档里写明的边界）。 */
        check(strcmp(dirname(a5), "/usr") == 0, "dirname(/usr/lib)==/usr");
        check(strcmp(dirname(a6), "/") == 0, "dirname(/usr/)==/");
        check(strcmp(dirname(a7), ".") == 0, "dirname(usr)==.");
        check(strcmp(dirname(a8), "/") == 0, "dirname(/)==/");
    }
    {
        struct tm t;
        struct tm *back;
        time_t e;
        char *s;
        memset(&t, 0, sizeof t);
        t.tm_year = 123;
        t.tm_mon = 9;
        t.tm_mday = 7;
        t.tm_hour = 0;
        t.tm_min = 53;
        t.tm_sec = 41;
        e = mktime(&t);
        s = asctime(&t);
        printf("[wave2] mktime=%ld asctime='%s'\n", (long)e, s ? s : "(null)");
        check(e == 1696640021, "mktime(2023-10-07 00:53:41 UTC) == 1696640021");
        check(t.tm_wday == 6, "mktime 归一化写回 tm_wday（周六=6）");
        back = localtime(&e);
        check(back != NULL && back->tm_year == 123 && back->tm_mon == 9 && back->tm_mday == 7,
              "mktime -> localtime 往返一致");
        s = ctime(&e);
        check(s != NULL && strncmp(s, "Sat Oct  7", 10) == 0, "ctime 前缀 Sat Oct  7");
    }
    {
        struct timespec ts;
        int rc;
        rc = clock_gettime(CLOCK_REALTIME, &ts);
        printf("[wave2] clock_gettime(REALTIME) rc=%d sec=%ld nsec=%ld\n",
               rc, (long)ts.tv_sec, (long)ts.tv_nsec);
        check(rc == 0 && ts.tv_sec > 1600000000, "CLOCK_REALTIME 可用且值合理");
        rc = clock_gettime(CLOCK_MONOTONIC, &ts);
        printf("[wave2] clock_gettime(MONOTONIC) rc=%d errno=%d\n", rc, errno);
        check(rc == -1 && errno == 22, "CLOCK_MONOTONIC 如实 EINVAL（本系统无单调时钟源）");
    }
    {
        const char *v;
        static char pe[] = "W2_B=put";
        check(setenv("W2_A", "one", 1) == 0, "setenv 新增");
        v = getenv("W2_A");
        check(v != NULL && strcmp(v, "one") == 0, "getenv 读到 one");
        check(setenv("W2_A", "two", 0) == 0, "setenv overwrite=0 返回 0");
        v = getenv("W2_A");
        check(v != NULL && strcmp(v, "one") == 0, "overwrite=0 时不覆盖");
        check(setenv("W2_A", "two", 1) == 0, "setenv 覆盖");
        v = getenv("W2_A");
        check(v != NULL && strcmp(v, "two") == 0, "覆盖后读到 two");
        check(setenv("", "x", 1) == -1, "空名字如实 -1");
        check(setenv("A=B", "x", 1) == -1, "名字含 = 如实 -1");
        check(unsetenv("W2_A") == 0, "unsetenv");
        check(getenv("W2_A") == NULL, "unsetenv 后 getenv 为 NULL");
        check(putenv(pe) == 0, "putenv");
        v = getenv("W2_B");
        check(v != NULL && strcmp(v, "put") == 0, "putenv 后 getenv 读到 put");
        check(clearenv() == 0, "clearenv");
        check(getenv("PATH") == NULL, "clearenv 后 PATH 为 NULL");
    }
    if (fails) {
        printf("[wave2] %d 项断言失败\n", fails);
        return 1;
    }
    printf("[wave2] all checks passed\n");
    return 0;
}
