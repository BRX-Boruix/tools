# BUILD —— 在 **BORUIX 机内**执行的构建配方（3P6-5「源码包在机编译」）。
#
# 约定：逐行、可直接粘进 Boruix shell；每条命令都在**系统内**跑（编译器是 tcc，
# 已在系统里；不依赖宿主）。宿主只负责把本目录整体分发到数据盘
# /volumes/BORUIX_DATA/3p/src/cowsay/。
#
# 产物落在 /volumes/BORUIX_DATA/3p/（与预编译 ELF 同一位置），故对调用方而言
# "源码分发"与"ELF 分发"产出的程序**同路径、同用法**。

cd /volumes/BORUIX_DATA/3p/src/cowsay
tcc cowsay.c -o /volumes/BORUIX_DATA/3p/cowsay
/volumes/BORUIX_DATA/3p/cowsay -w 30 hello from a source package built on the machine
