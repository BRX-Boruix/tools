# libcc1 —— C1 批 libc 面的系统内运行时验收

3P6-2 第二波（C1 批）的验收程序。**在 BORUIX 内**用 tcc 编译并运行，逐条打印 ok/FAIL。

## 覆盖项

memalign / valloc / strptime / fnmatch / glob / getopt / getopt_long /
regcomp+regexec+regerror+regfree / sigsetjmp+siglongjmp / tmpfile / on_exit+atexit 的 LIFO 顺序。

## 为什么需要它

`libc/tools/audit_posix_surface.py` 用 llvm-nm 读 libc.a，只能证明**符号存在**、
**头文件声明齐全**（PHANTOM/未声明两类缺陷）。它**证明不了行为对**——
例如 `tmpfile` 是不是真的可读可写、`fnmatch` 的 `FNM_PATHNAME` 是不是真的不跨 `/`。
那些只能在系统内真跑一遍才知道。

## 运行方式

宿主侧分发源码包（不编译）：

    python tools/main.py b3p --src --prog libcc1

机内按 `BUILD` 编译并运行（`BORUIX_INIT_RUN` 通道即可自动化）。
