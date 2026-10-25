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

**`-test` 模式的判决行**：内核自测套件尾部会打印 `[kt] DONE: executed=N declared=M`
（非破坏性测试全部跑完），脚本以它作为停止条件。没有这行时只能等 `run exited with code`
——那是 libccheck 的格式，`-test` 永远不会出现，于是**必然**被读成"卡死/失败"
（2026-10-25 就因此误判过一次，见 `docs/evidence/README.md`）。

**分片与单条复现**（构建期注入，`option_env!`；本内核没有运行时环境变量）：

```powershell
# 只跑一条（复现单条挂死：分钟级）
.\tools\devcheck\lc_run.ps1 -label one -test -ktOnly test_waitpid_e2e
# 把全量拆成 4 片，跑第 0 片
.\tools\devcheck\lc_run.ps1 -label shard0 -test -ktShard 0/4
```

套件里每条测试都有 `[kt] >> #i name` / `[kt] << #i name` 标记：**卡死时最后一条没有配对
`<<` 的就是凶手**，比"整体无输出"有用得多。

### `chk.py` —— 编译检查

```powershell
python tools\devcheck\chk.py kernel
python tools\devcheck\chk.py kernel-tests
python tools\devcheck\chk.py test-features   # 逐个 kernel-test* feature 各一次 cargo check
python tools\devcheck\chk.py crate shell
```

**`test-features` 为什么存在**：内核的停机验收测试各自挂在一个 `kernel-test-*` feature
后面，而日常只跑 `kernel-tests`——那些 feature 里的代码**可能长期没被编译过**。
2026-10-25 实测抓到三处：`kernel-test-m5` 引用了作用域里不存在的 `nr`，
`kernel-test-m43`/`kernel-test-m44` 还在用 `loader::load` 的旧 3 参形态（现 7 参）。
三者都修了，并且这条门禁让「测试腐烂」不能再静默发生。

feature 清单**从 `kernel/Cargo.toml` 的 `[features]` 解析**，不硬编码——硬编码清单
本身就是下一个漂移源（新加一个停机验收 feature 会被漏掉）。

### `kt_features.ps1` —— 停机验收 feature 的**运行**覆盖

```powershell
.\tools\devcheck\kt_features.ps1              # 全部 12 个配置各跑一次
.\tools\devcheck\kt_features.ps1 -only m43     # 只跑一个
```

内核的停机验收测试各自编码在**不同的 kernel** 里（一个 feature 一个 build），跑完就停机，
所以不能共享一次启动。这个脚本做的就是「逐个 build + boot + 跑 + 停」。

它补的是 `chk.py test-features` 补不上的那一半：`test-features` 只证明这些代码**编译**得过，
没有任何东西证明它们**跑**得起来——`kernel-test-m43/m44` 就是这样烂了几个月的。

判决口径（脚本**不发明 PASS**）：打印每个配置的行数、`: FAIL` 数、panic 数、`[kt] >>` 标记数
与最后两行非空输出；判定由人读完日志后写进文档。停机测试没有 verdict 行可等，故停止规则是
「QEMU 已启动（日志出现 `QEMU`）、之后日志静默 `-idleSec` 秒」，或到 `-perTestSec` 硬上限。

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
- `.out/` 会随运行累积，但它不是仓库内容，随时可以整个删掉。跑出结论时脚本会顺手删掉
  QEMU 的 stderr（每次约 650 KB 的近似重复噪声），只在没跑出结论时保留它。
- **`.ps1` 必须纯 ASCII。** 本机 PowerShell 是 5.1，它把无 BOM 的 UTF-8 当 ANSI 读；
  中文字节会把后面的引号吃掉，导致解析错乱——症状是脚本把自己的源码当字符串打出来、
  变量里的 `$` 全部消失。中文说明写进本文件或 `.py`，不要写进 `.ps1`。
