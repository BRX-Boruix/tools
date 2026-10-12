/* mode_umask_check.c —— mode 约定适配 + umask 的机内验收（tcc 编译，链 libc.a）。
 *
 * **判据用 stat 的 mode 位**，不用 access 探测——原因是本轮实测发现：
 * 内核 sys_open **不查 Permissions**（权限只被记录、不参与拦截）⇒ access(W_OK) 恒成功。
 * 那是**独立于本项的发现**，已登记；本文件只验「mode/umask 是否被**如实记录**」。
 */
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>

static int fails = 0;
static void ck(const char* what, int ok) {
    printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok) fails++;
}

#define DIR "/volumes/BORUIX_DATA/3p/mumask_d"
#define F1  "/volumes/BORUIX_DATA/3p/mumask_f1"
#define F2  "/volumes/BORUIX_DATA/3p/mumask_f2"

static unsigned int mode_of(const char* p) {
    struct stat st;
    if (stat(p, &st) != 0) return 0xFFFFFFFFu;
    return st.st_mode & 0777;
}

int main(void) {
    (void)unlink(F1); (void)unlink(F2); (void)rmdir(DIR);

    ck("默认 umask == 0（不静默改变既有行为）", umask(0) == 0);

    /* 1. mkdir(0755)：owner 应 rwx。改动前最低 3 位解出 (r,-,x) ⇒ owner w 位丢。 */
    ck("mkdir(0755) 成功", mkdir(DIR, 0755) == 0);
    ck("mkdir(0755) 记录 owner 可写（S_IWUSR）", (mode_of(DIR) & S_IWUSR) != 0);
    ck("mkdir(0755) 记录 owner 可读（S_IRUSR）", (mode_of(DIR) & S_IRUSR) != 0);
    ck("mkdir(0755) 记录 owner 可执行（S_IXUSR）", (mode_of(DIR) & S_IXUSR) != 0);

    /* 2. open(O_CREAT|O_RDONLY, 0600)：权限取自 mode ⇒ owner rw。改动前最低 3 位全 0。 */
    int fd = open(F1, O_CREAT | O_RDONLY, 0600);
    ck("open(O_CREAT|O_RDONLY, 0600) 成功", fd >= 0);
    if (fd >= 0) close(fd);
    ck("0600 记录 owner 可写", (mode_of(F1) & S_IWUSR) != 0);
    ck("0600 记录 owner 可读", (mode_of(F1) & S_IRUSR) != 0);

    /* 3. umask(0200) 清 owner 写 ⇒ 新文件**记录**里 owner 不可写（可观测）。 */
    ck("umask(0200) 返回旧值 0", umask(0200) == 0);
    (void)unlink(F2);
    fd = open(F2, O_CREAT | O_RDONLY, 0600);
    ck("umask 后 open 仍成功", fd >= 0);
    if (fd >= 0) close(fd);
    ck("umask(0200) 后 owner 写位被清（掩码可观测）", (mode_of(F2) & S_IWUSR) == 0);
    ck("umask(0200) 后 owner 读位仍在", (mode_of(F2) & S_IRUSR) != 0);
    ck("umask(0) 返回 0200", umask(0) == 0200);

    /* 4. 诚实边界：清组/其他的掩码不可观测（内核不表示 owner/group/other）。 */
    ck("umask(022) 返回 0", umask(022) == 0);
    (void)rmdir(DIR);
    ck("mkdir(0755) 在 umask 022 下 owner 位不变（组/其他不可表示）",
       mkdir(DIR, 0755) == 0 && (mode_of(DIR) & S_IRWXU) == S_IRWXU);
    (void)umask(0);

    (void)rmdir(DIR); (void)unlink(F1); (void)unlink(F2);
    printf("mode_umask_check: fails=%d\n", fails);
    return fails;
}