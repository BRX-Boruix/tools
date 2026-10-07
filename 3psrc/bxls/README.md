# bxls（BORUIX 源码包）

BORUIX 的一个 **ls**：列目录、长格式（权限/链接数/属主/大小/时间）。

它同时是 **3P6-2（libc 宽度第二波）的真实驱动之二**：ls 这类程序会一次用到
目录流（dirent）、stat、用户库（pwd）、时间格式化（localtime/strftime）与格式化输出
（snprintf），所以"能不能编过、跑对"直接反映 libc 的宽度，而不是靠清单去猜。

## 目录内容

| 文件 | 作用 |
| --- | --- |
| `bxls.c` | 入口源文件 |
| `BUILD` | **在机内**执行的构建配方 |
| `README.md` | 本说明 |

## 用法

```sh
bxls                 # 列当前目录
bxls -a              # 含隐藏项
bxls -l /path        # 长格式
```
