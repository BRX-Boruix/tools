/* bxls.c —— 3P6-2 第二波的真实驱动之二：一个**真正可用**的 ls（Boruix 版）。
 *
 * 为什么是它：第二波的判据是「按真实报错补，不预猜」，所以需要一个**真实会用到**
 * 目录/stat/用户库/时间/格式化这一整片的程序。ls 正是这种程序，而且它本身就是
 * 系统里缺的一个常用工具——不是为测试而造的壳。
 *
 * 用法：
 *   bxls                 # 列当前目录
 *   bxls /path [more...] # 列指定目录
 *   bxls -a              # 含隐藏项
 *   bxls -l              # 长格式（权限/链接数/属主/大小/时间）
 *
 * 退出码：0 成功；1 有路径打不开；2 用法错误。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>
#include <pwd.h>

#define MAX_ENT 512
#define NAME_CAP 256
#define PATH_CAP 1024

static char g_names[MAX_ENT][NAME_CAP];
static int  g_nent = 0;

static int cmp_name(const void *a, const void *b) {
    return strcmp((const char *)a, (const char *)b);
}

/* "drwxr-xr-x" 形式的权限串。本系统没有组/其他权限位（见 sys/stat.h 的说明），
 * 故那两组位如实镜像 owner——头文件已声明这一点，这里不另造语义。 */
static void mode_str(unsigned int m, char *out) {
    static const char rwx[] = "rwx";
    int i;
    if (S_ISDIR(m))       out[0] = 'd';
    else if (S_ISLNK(m))  out[0] = 'l';
    else if (S_ISCHR(m))  out[0] = 'c';
    else if (S_ISBLK(m))  out[0] = 'b';
    else if (S_ISFIFO(m)) out[0] = 'p';
    else if (S_ISSOCK(m)) out[0] = 's';
    else                  out[0] = '-';
    for (i = 0; i < 9; i++)
        out[1 + i] = (m & (1u << (8 - i))) ? rwx[i % 3] : '-';
    out[10] = 0;
}

static void join_path(char *dst, size_t cap, const char *dir, const char *name) {
    if (strcmp(dir, ".") == 0)
        snprintf(dst, cap, "%s", name);
    else
        snprintf(dst, cap, "%s/%s", dir, name);
}

static void print_long(const char *dir, const char *name) {
    char path[PATH_CAP];
    char mb[16];
    char tbuf[64];
    struct stat st;
    struct tm *tmv;
    struct passwd *pw;

    join_path(path, sizeof path, dir, name);
    if (stat(path, &st) != 0) {
        printf("%-10s %-8s %8s %-16s %s\n", "??????????", "?", "?", "?",
               name);
        return;
    }
    mode_str(st.st_mode, mb);
    pw = getpwuid(st.st_uid);
    tmv = localtime(&st.st_mtime);
    if (tmv != NULL && strftime(tbuf, sizeof tbuf, "%Y-%m-%d %H:%M", tmv) == 0)
        snprintf(tbuf, sizeof tbuf, "%s", "?");
    if (tmv == NULL)
        snprintf(tbuf, sizeof tbuf, "%s", "?");
    printf("%s %3lu %-8s %8ld %s %s%s\n",
           mb, (unsigned long)st.st_nlink,
           (pw != NULL) ? pw->pw_name : "?",
           (long)st.st_size, tbuf, name,
           S_ISDIR(st.st_mode) ? "/" : "");
}

static int list_dir(const char *dir, int longfmt, int all) {
    DIR *d;
    struct dirent *e;
    int i;
    int rc = 0;

    d = opendir(dir);
    if (d == NULL) {
        printf("bxls: %s: %s\n", dir, strerror(errno));
        return 1;
    }
    g_nent = 0;
    while ((e = readdir(d)) != NULL) {
        if (!all && e->d_name[0] == '.')
            continue;
        if (g_nent >= MAX_ENT) {
            printf("bxls: %s: too many entries (>%d)\n", dir, MAX_ENT);
            rc = 1;
            break;
        }
        strncpy(g_names[g_nent], e->d_name, NAME_CAP - 1);
        g_names[g_nent][NAME_CAP - 1] = 0;
        g_nent++;
    }
    closedir(d);
    qsort(g_names, (size_t)g_nent, NAME_CAP, cmp_name);

    if (longfmt) {
        printf("%s:\n", dir);
        for (i = 0; i < g_nent; i++)
            print_long(dir, g_names[i]);
    } else {
        for (i = 0; i < g_nent; i++)
            printf("%s\n", g_names[i]);
    }
    return rc;
}

int main(int argc, char **argv) {
    int longfmt = 0;
    int all = 0;
    int npath = 0;
    int rc = 0;
    int i;

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (strcmp(a, "-l") == 0) {
            longfmt = 1;
        } else if (strcmp(a, "-a") == 0) {
            all = 1;
        } else if (strcmp(a, "-la") == 0 || strcmp(a, "-al") == 0) {
            longfmt = 1;
            all = 1;
        } else if (a[0] == '-' && a[1] != 0) {
            printf("bxls: unknown option: %s\n", a);
            return 2;
        } else {
            if (list_dir(a, longfmt, all) != 0)
                rc = 1;
            npath++;
        }
    }
    if (npath == 0)
        rc = list_dir(".", longfmt, all);
    return rc;
}
