/* syscallfuzz.c —— 从用户态灌**非法参数**，按"是否真能 panic 内核"给 panic 面排序。
 *
 * 为什么需要它：内核里 panic!/expect/unwrap 有数百处，盲修不现实。真正要回答的是
 * **哪些能从用户态到达**——那就用真实调用去撞，而不是读代码猜。
 *
 * 纪律：
 *   - 每一步**先打印步骤名再调用**，故内核若 panic，串口上最后一行就是肇事步骤；
 *   - 每一步都用**非法/边界**参数（负 fd、超大 pid、NULL 指针、0/极大长度、越界命令）；
 *   - 不假设哪个会崩：全部跑一遍，让证据说话。
 */
extern int printf(const char *, ...);
extern long write(int fd, const void *buf, unsigned long n);
extern long read(int fd, void *buf, unsigned long n);
extern int open(const char *path, int flags, ...);
extern int close(int fd);
extern long lseek(int fd, long off, int whence);
extern int waitpid(int pid, int *status, int options);
extern int kill(int pid, int sig);
extern int dup2(int oldfd, int newfd);
extern int fcntl(int fd, int cmd, ...);
extern int chdir(const char *path);
extern int unlink(const char *path);
extern int rmdir(const char *path);
extern void *mmap(void *addr, unsigned long len, int prot, int flags, int fd, long off);
extern int munmap(void *addr, unsigned long len);
extern int mprotect(void *addr, unsigned long len, int prot);
extern int fstat(int fd, void *st);
extern long sysconf(int name);
extern int getpid(void);

#define STEP(name) do { printf("[fz] %s\n", name); } while (0)

int main(void) {
    static char buf[64];
    int st;

    STEP("waitpid 非法 pid");
    waitpid(-999999, &st, 0);
    waitpid(999999999, &st, 0);
    waitpid(0, &st, 0);
    waitpid(getpid(), &st, 0);
    waitpid(-1, 0, 0);
    waitpid(1, &st, 0);

    STEP("waitpid 非法 options");
    waitpid(-1, &st, 0x7fffffff);
    waitpid(-1, &st, -1);

    STEP("kill 非法");
    kill(-999999, 9);
    kill(999999999, 9);
    kill(0, 0);
    kill(getpid(), 0);

    STEP("read/write 非法 fd");
    read(-1, buf, 8);
    write(-1, buf, 8);
    read(999999, buf, 8);
    write(999999, buf, 8);
    read(1, buf, 8);
    write(0, buf, 8);

    STEP("lseek 非法");
    /* **绝不 lseek(1, ...)**：本程序的 printf 走 fd 1，把它的偏移设到极大之后
       所有后续输出都写不进去，后续步骤的证据会**全部丢失**（首版就栽在这里：
       日志停在 "lseek 非法" 之后，看起来像内核挂了，其实是 fixture 自己把
       stdout 弄没了）。非法 fd 与越界 whence 已足够覆盖这一路。 */
    lseek(-1, 0, 0);
    lseek(999999, 0, 0);
    lseek(999999, 0, 99);
    lseek(-1, 0x7fffffffffffffffL, 0);
    lseek(-1, -1, 1);

    STEP("open 非法");
    open("", 0);
    open("/nonexistent-xyz", 0);
    open("/volumes", 0);
    open(0, 0);

    STEP("close 非法");
    close(-1);
    close(999999);
    /* 注意：**不** close(1)——那会让本程序其后的所有 printf 都无处可去，
       后续步骤的证据全丢。非法 fd 已经足够覆盖这一路。 */

    STEP("dup2 非法");
    dup2(-1, 5);
    dup2(999999, 5);
    dup2(1, -1);
    dup2(1, 999999);
    dup2(1, 1);

    STEP("fcntl 非法");
    fcntl(-1, 0);
    fcntl(999999, 0);
    fcntl(1, 0x7fff);

    STEP("chdir/unlink/rmdir 非法");
    chdir("/nonexistent-xyz");
    chdir("");
    unlink("/nonexistent-xyz");
    unlink("/volumes");
    rmdir("/volumes");
    rmdir("/nonexistent-xyz");

    STEP("mmap 非法");
    mmap(0, 0, 3, 0x22, -1, 0);
    mmap(0, 0x7fffffffffffffffL, 3, 0x22, -1, 0);
    mmap((void *)0x1000, 4096, 3, 0x22, -1, 0);
    mmap(0, 4096, 0x7f, 0x22, -1, 0);
    mmap(0, 4096, 3, 0, -1, 0);

    STEP("munmap/mprotect 非法");
    munmap(0, 4096);
    munmap((void *)0xdead0000, 0);
    munmap((void *)0xdead0000, 0x7fffffffffffffffL);
    mprotect(0, 4096, 3);
    mprotect((void *)0xdead0000, 4096, 3);

    STEP("fstat 非法");
    fstat(-1, buf);
    fstat(999999, buf);
    fstat(1, 0);

    STEP("sysconf 非法");
    sysconf(-1);
    sysconf(999999);

    STEP("全部完成");
    printf("syscallfuzz: survived\n");
    return 0;
}
