# devcheck —— 开发期验证脚手架

这里放**会反复使用的**验证入口。一次性脚本不进这里，用完即删。

## 准入规则

| 类别 | 去处 |
|---|---|
| 会再跑第二次的 | 这个目录，有名字、有参数、有说明 |
| 只跑一次的改写/统计脚本 | 用完即删；成果在 commit 里，commit message 就是它的记录 |
| 编译/运行日志 | `.out/`（gitignore），不是工作区根目录 |
| 支撑某条结论的原始输出 | `docs/evidence/`，并登记在那一页的索引里 |

这条规则的来源：`.tmp-audit/` 曾同时装着工具、证据、日志和源码快照，
删掉之前已经分不清哪个是哪个——**没有准入规则的地方，什么都会进来。**

## 工具

### `lc_run.ps1` —— 机内验收运行器

一次 QEMU 启动跑完 libccheck 或内核自测，然后收割结论行。

```powershell
.\tools\devcheck\lc_run.ps1 -label postmove
.\tools\devcheck\lc_run.ps1 -label kt -test
.\tools\devcheck\lc_run.ps1 -label diskless -testdisk -noRedisk -mem 768M
```

取代了此前 `lc_run` / `lc_run256` / `lc_run768` / `lc512` / `lc_test_run` /
`nsdbg_run` 一批近乎相同的副本——它们的差别只是内存大小、`--test`、`--redisk`，
那些现在都是参数。

### `chk.py` —— 编译检查

```powershell
python tools\devcheck\chk.py kernel
python tools\devcheck\chk.py kernel-tests
python tools\devcheck\chk.py crate shell
```

### `verify_precond.py` —— 门禁前置探测的场景验证

```powershell
python tools\devcheck\verify_precond.py
```

三种场景：无前置必须全 SKIP 且整体非 0；前置坏掉必须 FAIL 而不是 SKIP；
前置真实存在时必须真的跑。场景 3 依赖环境里已有的 `BORUIX_SYSROOT`，缺失时
明确跳过并打印原因，不伪造前置。

### `all_repos.ps1` —— 全部 git 仓库状态

```powershell
.\tools\devcheck\all_repos.ps1
```

列出未推送提交、脏工作区、无远端的仓库。

## 约定

- 所有脚本按自身位置推出工作区根（`<root>/tools/devcheck/`），**不依赖调用者的 cwd**。
- 日志只写 `.out/`，不写工作区根，不产生 `.tmp-` 前缀文件。
- 退出码即结论：0 通过，非 0 失败。不打印「看起来成功」的伪结论。
- **`.ps1` 必须纯 ASCII。** 本机 PowerShell 是 5.1，它把无 BOM 的 UTF-8 当 ANSI 读；
  中文字节会把后面的引号吃掉，导致解析错乱——症状是脚本把自己的源码当字符串打出来、
  变量里的 `$` 全部消失。中文说明写进本文件或 `.py`，不要写进 `.ps1`。
