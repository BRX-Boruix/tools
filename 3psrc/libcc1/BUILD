# BUILD —— 在 **BORUIX 机内**执行的构建配方（3P6-5「源码包在机编译」）。
#
# 约定：逐行、可直接粘进 Boruix shell；每条命令都在**系统内**跑（编译器是 tcc）。
# 宿主只负责把本目录整体分发到数据盘 /volumes/BORUIX_DATA/3p/src/libcc1/。
#
# 本包是 3P6-2 第二波（C1 批）的**运行时验收**：反向对账只能证明符号存在与声明齐全，
# 证明不了行为对；这里在系统内真跑一遍每个 C1 项，逐条打印 ok/FAIL。

cd /volumes/BORUIX_DATA/3p/src/libcc1
tcc libcc1.c -o /volumes/BORUIX_DATA/3p/libcc1
/volumes/BORUIX_DATA/3p/libcc1
