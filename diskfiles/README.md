# diskfiles/

数据盘 `disk.img` 的**内容来源**。构建时本目录被递归读取，
按原有目录结构写入 `disk.img` 的 EXT2 文件系统。

## 用法

    python main.py mkimg

容量默认按内容自动推算（含 EXT2 元数据与间接块开销 + 余量），
需要固定大小时用 `--size N` 覆盖。

## 约定

- 本目录**只读**：构建只读取它，产出物只有 `disk.img`，
  重复构建的结果只取决于本目录的内容。
- 目录结构会被保留。`sub/dir/a.txt` 在盘上是 `/sub/dir/a.txt`。
- 构建结果是确定的：文件按名称排序写入，同样的输入产出同样的盘。
- 空目录或不存在会**如实报错**，不产出一张空盘——
  空盘会被误认为「内容已写入」。

## 只读挂载后的样子

ISO 启动（liveCD）时，本盘作为卷挂到 `/volumes/{label}`；
从 `systemdisk.img` 启动时同样挂到 `/volumes/{label}`。

用 `ls /volumes/` 查看卷标，`cat /volumes/BORUIX_DATA/<文件>` 读取内容。
