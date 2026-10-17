/* forkmin.c —— fork/waitpid 挂起的**最小复现**（目标第 2~4 轮）。
 *
 * 已确认的事实：
 *   - 裸 fork + 子 _exit(42) + 父 waitpid：**通过**（第 2 轮）。
 *   - 只要在 fork 前 malloc 并**逐页触碰** 16 KB（4 页堆，地址 0x100000010 = USER_HEAP_BASE+0x10）：
 *     **挂起**（第 3 轮；fork 已返回、子进程跑到 _exit 前一行、父进程 waitpid 再不返回）。
 *   - BSS 加减 8 KB 无影响（第 1 轮）——因为 BSS 不是堆。
 *
 * 用法（argv）：
 *   forkmin                     裸跑（不 malloc）
 *   forkmin <KB>                malloc 并逐页触碰 <KB> 后 fork（直接 worker）
 *   forkmin worker <KB> [alloc] worker 形态；带 alloc 表示**只 malloc 不触碰**（对照组）
 *   forkmin nowait <KB> [alloc] fork 出 worker 后**父进程立刻返回**
 *
 * 为什么要有 nowait：一个用例挂起会让 shell 卡在分号处、后面的用例跑不到。
 * nowait 让 shell 立刻继续，各 worker 并发跑，于是一次启动就能拿到全部尺寸的结果：
 * 日志里打印了 "waitpid ->" 的 tag 是通过的，停在 "fork returned" 的是挂起的。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>

static char *touch_kb(long kb, int do_touch) {
    long n = kb * 1024;
    char *p;
    long i;
    if (kb <= 0) {
        return (char *)1; /* 非 NULL 哨兵：表示没有分配 */
    }
    p = (char *)malloc((size_t)n);
    if (p == NULL) {
        return NULL;
    }
    if (do_touch) {
        for (i = 0; i < n; i += 4096) {
            p[i] = (char)(i & 0x7f);
        }
    }
    return p;
}

/* 一个用例：触碰 -> fork -> 子 _exit(42) -> 父 waitpid。每步 fflush，日志能精确定位。 */
static int worker(long kb, int do_touch, const char *tag) {
    char *blob;
    int pid;
    int st = 0;
    int got;

    blob = touch_kb(kb, do_touch);
    if (blob == NULL) {
        printf("[%s] malloc %ld KB FAILED\n", tag, kb);
        fflush(stdout);
        return 2;
    }
    printf("[%s] touched=%d kb=%ld\n", tag, do_touch, kb);
    fflush(stdout);

    pid = fork();
    if (pid == 0) {
        printf("[%s] child exiting 42\n", tag);
        fflush(stdout);
        _exit(42);
    }
    printf("[%s] fork returned %d\n", tag, pid);
    fflush(stdout);

    got = waitpid(pid, &st, 0);
    printf("[%s] waitpid -> %d status=%d code=%d\n", tag, got, st, WEXITSTATUS(st));
    fflush(stdout);

    if (got == pid && WIFEXITED(st) && WEXITSTATUS(st) == 42) {
        printf("[%s] OK\n", tag);
        return 0;
    }
    printf("[%s] FAIL\n", tag);
    return 1;
}

int main(int argc, char **argv) {
    long kb = 0;
    int do_touch = 1;

    if (argc >= 2 && strcmp(argv[1], "worker") == 0) {
        kb = (argc >= 3) ? atol(argv[2]) : 0;
        if (argc >= 4 && strcmp(argv[3], "alloc") == 0) {
            do_touch = 0;
        }
        return worker(kb, do_touch, (argc >= 3) ? argv[2] : "0");
    }
    if (argc >= 3 && strcmp(argv[1], "nowait") == 0) {
        kb = atol(argv[2]);
        if (argc >= 4 && strcmp(argv[3], "alloc") == 0) {
            do_touch = 0;
        }
        printf("[main] spawn kb=%ld touch=%d\n", kb, do_touch);
        fflush(stdout);
        if (fork() == 0) {
            _exit(worker(kb, do_touch, argv[2]));
        }
        return 0;
    }
    if (argc >= 2) {
        kb = atol(argv[1]);
    }
    return worker(kb, do_touch, (argc >= 2) ? argv[1] : "0");
}
