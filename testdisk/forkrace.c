/* forkrace.c —— waitpid panic 的复现/回归器（两个形态都跑）。
 *
 * 目标缺陷（两处，同一族）：
 *   A. waitpid_probe / waitpid_inner 的 WAIT_ANY 分支：持锁扫描 → **释放桶锁** →
 *      reap_child_locked 重取锁收割。窗口内子进程的退出路径（另一核）可能已摘除表项
 *      ⇒ reap 返回 None ⇒ .expect("zombie confirmed") **panic 内核**。
 *   B. terminate 里 parent_reapable(ppid) 与 proc_bucket_lock(ppid).get_mut(..)
 *      .expect("parent reapable") 之间是 TOCTOU：父进程可能已被收尸。
 *
 * 形态 1（快子进程）：子进程立刻 _exit —— 覆盖"父未阻塞、子已 zombie"的常规路径。
 * 形态 2（慢子进程）：子进程先忙等一会儿再 _exit —— 让父进程**先进入阻塞等待**，
 *   从而踩到"父已登记 + 子正在退出"那条窄窗口（形态 1 到不了）。
 */
extern int printf(const char *, ...);
extern int fork(void);
extern int waitpid(int pid, int *status, int options);
extern void _exit(int code);

static void burn(int n) {
    volatile int x = 0;
    int i;
    for (i = 0; i < n; i++) {
        x += i;
    }
}

#define ROUNDS 200

int main(void) {
    int i;
    int bad = 0;

    /* 形态 1：快子进程 */
    for (i = 0; i < ROUNDS; i++) {
        int pid = fork();
        if (pid == 0) {
            _exit(42);
        }
        if (pid < 0) {
            bad++;
            continue;
        }
        {
            int st = 0;
            if (waitpid(pid, &st, 0) != pid) {
                bad++;
            }
        }
    }
    printf("forkrace: fast rounds=%d bad=%d\n", ROUNDS, bad);

    /* 形态 2：慢子进程（父会先阻塞） */
    for (i = 0; i < ROUNDS; i++) {
        int pid = fork();
        if (pid == 0) {
            burn(200000);
            _exit(43);
        }
        if (pid < 0) {
            bad++;
            continue;
        }
        {
            int st = 0;
            if (waitpid(pid, &st, 0) != pid) {
                bad++;
            }
        }
    }
    printf("forkrace: slow rounds=%d bad=%d\n", ROUNDS, bad);
    printf("forkrace: done\n");
    return 0;
}
