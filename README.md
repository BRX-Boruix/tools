# tools

BORUIX 的系统工具：编译内核、打包可引导镜像、在虚拟机里运行并做验收。

[English](README.en.md)

```bash
python main.py build      # 编译内核，生成可引导 ISO
python main.py run        # 用 QEMU 启动
python main.py br         # 编译加启动，一步到位
```

## 子命令

- `build`——编译内核并生成可引导 ISO
- `run`——用 QEMU 启动 ISO，可指定内存大小（默认 128M）与串口输出
- `br`——`build` 加 `run`，日常开发最常用
- `mkimg`——创建 EXT2 数据盘镜像，可指定卷标
- `limine-build`——交叉编译引导程序的早期阶段
- `b3p`——构建登记在册的第三方程序并放入数据盘

## 引导镜像的组成

ISO 由内核与引导程序两部分组成。内核经两遍链接：先链接一次得到符号表，再带着符号表编译一遍，
因为部分数据结构的布局依赖符号地址。引导程序使用本项目的分支，其早期阶段由交叉编译器构建。

## 数据盘

`mkimg` 生成 EXT2 镜像，`diskfiles/` 下的内容会放入其中：测试音频文件、示例程序，以及一组用于
验证目录遍历的嵌套目录。最大的一个音频文件因体积不入库，需自行准备。

## 验收脚本

`checks/` 下有 23 个验收脚本，按域分类：

- `boot`——开机序列、系统盘安装、终端创建、打字风暴
- `interactive`——真实按键交互的逐层验证
- `terminal`——终端挂载、焦点、轮转、并行实例
- `process`——进程批量启动、控制台服务、看门狗
- `ievents`——输入事件链路
- `regression`——自检全量、中断响应、调度器、指令集回归

脚本只走真实链路：键盘输入经虚拟机监控接口注入真实 PS/2 扫描码，崩溃判定读串口日志的实际输出。
一个「通过」意味着真实链路上确实成功。

## 构建

需要 Python 3 与 QEMU。运行 `python main.py --help` 查看全部子命令。

## 文件结构

```
tools/
├── main.py           # 命令入口
├── tools_build/      # 构建与打包实现
├── checks/           # 验收脚本，按域分类
├── diskfiles/        # 放入数据盘的内容
└── limine.conf       # 引导程序配置
```

## 相关项目

- [`init`](https://github.com/BRX-Boruix/init) —— 系统初始化进程
- [`selftest`](https://github.com/BRX-Boruix/selftest) —— 系统自检程序
- [`sdk`](https://github.com/BRX-Boruix/sdk) —— 面向第三方开发者的交叉编译工具

## 许可

MIT License，版权归 Yang Borui 所有。详见 [LICENSE](LICENSE)。
