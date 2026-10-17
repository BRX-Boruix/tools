/* dlclose_check.c —— RTLD_NOLOAD 与 dlclose 的机内验收。
 *
 * 为什么需要：此前 `dlopen` 把 flags **整个忽略**（`let _ = flags;`），于是
 * `RTLD_NOLOAD`（"只查已装载对象、不装载"）被当成普通 dlopen ⇒ **又装载了一份**，
 * 同一个 .so 在符号表里出现两份、第二次的句柄指向新对象。`dlclose` 则**符号都不存在**
 * （调用即链接失败）。
 */
#include <stdio.h>
#include <dlfcn.h>

static int fails = 0;
static void chk(const char *what, int ok) {
    if (!ok) { fails++; printf("FAIL %s\n", what); } else { printf("ok   %s\n", what); }
}

int main(void) {
    void *h1 = dlopen("/volumes/BORUIX_DATA/3p/libadd.so", RTLD_NOW);
    chk("首次 dlopen 成功", h1 != 0);
    if (!h1) { printf("dlclose_check: fails=%d\n", fails); return 1; }

    void *h2 = dlopen("/volumes/BORUIX_DATA/3p/libadd.so", RTLD_NOW | RTLD_NOLOAD);
    chk("RTLD_NOLOAD 返回**既有**句柄（不重复装载）", h2 == h1);

    void *h3 = dlopen("/volumes/BORUIX_DATA/3p/libtls.so", RTLD_NOW | RTLD_NOLOAD);
    chk("RTLD_NOLOAD 对未装载的 .so 返回 NULL（不装载）", h3 == 0);

    chk("dlclose(有效句柄) == 0", dlclose(h1) == 0);
    chk("dlclose(NULL) == -1（句柄非法）", dlclose(0) == -1);

    printf("dlclose_check: fails=%d\n", fails);
    return fails ? 1 : 0;
}