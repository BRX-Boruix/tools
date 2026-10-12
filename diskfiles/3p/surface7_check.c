/* surface7_check.c —— libc 表面收口批的机内验收（tcc 编译，链 libc.a）。
 *
 * 验的是「符号存在」之上的那一层：**能用**。
 *   1. boruix_memory_query：对一个已知已映射的地址（本函数的栈变量）应报 PRESENT|USER|WRITABLE；
 *      对明显未映射的高地址应报 0（且**不**触发补页）。
 *   2. nl_langinfo：CODESET / D_T_FMT / DAY_1 / MON_1 / RADIXCHAR / YESEXPR 取 C locale 规范值。
 *   3. confstr：_CS_PATH 与 _CS_GNU_LIBC_VERSION 有值；未定义的 name 返回 0。
 *   4. sem_*：单线程语义（init/post/wait/trywait/getvalue/destroy）逐条断言。
 *      **多线程唤醒不在此验**（那是 csrc 侧 pthreaddemo 的活）；这里验的是「同一套语义在 libc.a 上可用」。
 */
#include <stdio.h>
#include <string.h>
#include <langinfo.h>
#include <unistd.h>
#include <semaphore.h>

/* 内核与 libsys 双侧定义的位值（boruix.h 目前不导出它们，故此处按契约取值）。 */
#define MEMQ_PRESENT  (1ULL << 0)
#define MEMQ_USER     (1ULL << 1)
#define MEMQ_WRITABLE (1ULL << 2)

int boruix_memory_query(const void* addr, unsigned long long* out);

static int fails = 0;
static void ck(const char* what, int ok) {
    printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok) fails++;
}

int main(void) {
    /* 1. memory_query */
    int local = 0;
    unsigned long long bits = 0;
    int rc = boruix_memory_query(&local, &bits);
    ck("memory_query(栈变量) rc==0", rc == 0);
    ck("memory_query 报 PRESENT", (bits & MEMQ_PRESENT) != 0);
    ck("memory_query 报 USER", (bits & MEMQ_USER) != 0);
    ck("memory_query 报 WRITABLE", (bits & MEMQ_WRITABLE) != 0);
    bits = 0xdeadbeefULL;
    rc = boruix_memory_query((const void*)0x7f0000000000ULL, &bits);
    ck("memory_query(未映射高地址) 位图为 0", rc == 0 && bits == 0);

    /* 2. nl_langinfo */
    ck("nl_langinfo(CODESET)==ASCII", strcmp(nl_langinfo(CODESET), "ASCII") == 0);
    ck("nl_langinfo(D_T_FMT) 非空", nl_langinfo(D_T_FMT)[0] != 0);
    ck("nl_langinfo(DAY_1)==Sunday", strcmp(nl_langinfo(DAY_1), "Sunday") == 0);
    ck("nl_langinfo(DAY_7)==Saturday", strcmp(nl_langinfo(DAY_7), "Saturday") == 0);
    ck("nl_langinfo(ABDAY_1)==Sun", strcmp(nl_langinfo(ABDAY_1), "Sun") == 0);
    ck("nl_langinfo(MON_1)==January", strcmp(nl_langinfo(MON_1), "January") == 0);
    ck("nl_langinfo(MON_12)==December", strcmp(nl_langinfo(MON_12), "December") == 0);
    ck("nl_langinfo(ABMON_12)==Dec", strcmp(nl_langinfo(ABMON_12), "Dec") == 0);
    ck("nl_langinfo(RADIXCHAR)==.", strcmp(nl_langinfo(RADIXCHAR), ".") == 0);
    ck("nl_langinfo(YESEXPR) 非空", nl_langinfo(YESEXPR)[0] != 0);
    ck("nl_langinfo(THOUSEP) 为空（C locale 确实无值）", nl_langinfo(THOUSEP)[0] == 0);

    /* 3. confstr */
    char buf[64];
    size_t n = confstr(1 /*_CS_PATH*/, buf, sizeof buf);
    ck("confstr(_CS_PATH) 有值", n > 1 && buf[0] == '/');
    n = confstr(2 /*_CS_GNU_LIBC_VERSION*/, buf, sizeof buf);
    ck("confstr(_CS_GNU_LIBC_VERSION) 含 boruix", n > 1 && strstr(buf, "boruix") != 0);
    ck("confstr(未定义 name)==0", confstr(9999, buf, sizeof buf) == 0);

    /* 4. sem_*（单线程语义） */
    static sem_t s;
    ck("sem_init 成功", sem_init(&s, 0, 1) == 0);
    int v = -1;
    ck("sem_getvalue 初值 1", sem_getvalue(&s, &v) == 0 && v == 1);
    ck("sem_wait 拿到令牌", sem_wait(&s) == 0);
    ck("sem_getvalue 归 0", sem_getvalue(&s, &v) == 0 && v == 0);
    ck("sem_trywait 无令牌时失败", sem_trywait(&s) == -1);
    ck("sem_post 成功", sem_post(&s) == 0);
    ck("sem_trywait 现在成功", sem_trywait(&s) == 0);
    ck("sem_destroy 成功", sem_destroy(&s) == 0);
    ck("destroy 后 wait 如实失败", sem_wait(&s) == -1);
    ck("pshared!=0 如实拒绝", sem_init(&s, 1, 1) == -1);

    printf("surface7_check: fails=%d\n", fails);
    return fails;
}