/* 编译期检查：<dlfcn.h> 存在、四个 RTLD_* 取值可用、四个函数可声明式引用。
 * 只做语法/类型检查（-fsyntax-only），不链接——本步只补声明面。 */
#include <dlfcn.h>
int main(void) {
    int flags = RTLD_NOW | RTLD_NOLOAD;
    void *(*p_open)(const char *, int) = dlopen;
    void *(*p_sym)(void *, const char *) = dlsym;
    int (*p_close)(void *) = dlclose;
    char *(*p_err)(void) = dlerror;
    (void)p_open; (void)p_sym; (void)p_close; (void)p_err;
    if (flags == (RTLD_LAZY | RTLD_GLOBAL | RTLD_LOCAL)) { return 1; }
    return 0;
}