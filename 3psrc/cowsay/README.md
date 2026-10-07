# cowsay（BORUIX 源码包）

这是 BORUIX **源码分发通道**（3P6-5）的第一个包：盘上只有源码与构建配方，
**没有预编译 ELF**；程序由系统内编译器（tcc）在机内编出来。

## 目录内容

| 文件 | 作用 |
| --- | --- |
| `cowsay.c` | 入口源文件（单文件，无外部依赖，只用 libc 的 stdio/stdlib/string） |
| `BUILD` | **在机内**执行的构建配方（逐行命令，可直接粘进 shell） |
| `README.md` | 本说明 |

## 分发与使用

宿主侧只铺源码（不编译）：

```sh
python tools/main.py b3p --src --prog cowsay     # 铺到 tools/diskfiles/3p/src/cowsay/
```

机内按 `BUILD` 编译并运行（`BORUIX_INIT_RUN` 通道即可自动化）：

```sh
cd /volumes/BORUIX_DATA/3p/src/cowsay
tcc cowsay.c -o /volumes/BORUIX_DATA/3p/cowsay
/volumes/BORUIX_DATA/3p/cowsay -w 30 hello from a source package
```

## 为什么与 `b3p` 的 ELF 通道并存

`b3p` 原通道面向 **Rust** 第三方程序：宿主 cargo 交叉编译出 `3p/<name>.elf` 再上盘。
那条路要求分发方持有工具链。源码包通道把"编译"搬到**目标机内**（本系统已能自举出
可用的 tcc），于是分发方只需要发源码——这正是 3P6-5 要扩展的那一环。
