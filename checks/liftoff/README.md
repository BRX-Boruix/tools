# liftoff 检查（gen2）

## 统一入口（A4）

```
python checks/run_all.py              # 只跑离线检查（秒级，12 项）
python checks/run_all.py --hardware   # 额外跑需要 QEMU 的检查（每次 5–10 分钟）
```

退出码 0 = 选中的检查**全部**通过；**空集合不算通过** ✗。新增检查**必须**登记进
`checks/run_all.py` 的 `OFFLINE_CHECKS` / `HARDWARE_CHECKS` ✓ —— 登记是强制的，
不靠"自动发现"（自动发现会让"改名后静默少跑"无法察觉 ✗）。

## 完整验证程序（改一处 liftoff 代码后，按此顺序跑）

**这一节是运维手册（S36）**：把散落的门禁串成一份**可照做**的清单 ✓。
**顺序有意义** —— 从便宜到贵 ✓：先抓编译与静态问题 ✓，最后才花 5–10 分钟跑 QEMU ✓。

### 第 0 步：闸门（**必须在 liftoff 目录**）

```bash
cd liftoff
cargo test                              # 必须退出 0
cargo build --release --target x86_64-unknown-uefi   # 必须退出 0
# 且两者**警告数必须为 0**（不是"看起来没有"✗ —— 数出来 ✓）
```

**⚠️ 退出码 0 不等于代码被编译** ✗ —— 本仓库出过一次"假绿"：整段汇编被夹在 `#[cfg(test)]` 模块里，
于是 UEFI 构建**根本没编译它**，而构建照样退出 0 ✓。所以第 1 步**必须**跑 ✓。

### 第 1 步：静态与离线（**在 tools 目录**，全部不需要 QEMU）

```bash
cd tools
python checks/liftoff/asm_check.py                      # PRE-1：反汇编产物，核对指纹指令与序列
python checks/regression/check_arch_isolation.py        # PRE-3：中立层无实现依赖
python checks/liftoff/mock_impl_check.py                # PRE-3：impl-mock 仍能编译
python checks/regression/check_catalog.py               # PRE-3：每个检查都已登记
python checks/regression/diag_selftest.py               # PRE-3：诊断模块离线自检
python checks/regression/iso9660_selftest.py            # PRE-3：ISO9660 解析器
python checks/regression/elf_image_selftest.py          # PRE-3：ELF64 解析器
python checks/regression/symbols_selftest.py            # PRE-3：地址→符号
python checks/regression/run_smp_selftest.py            # PRE-3：--smp → QEMU 参数
python checks/regression/config_paths_selftest.py       # PRE-3：S01 路径派生
python checks/regression/test_module_leak_selftest.py   # PRE-3：防假绿（pub 项不得在测试模块里）
python checks/regression/selftest_registry_check.py     # PRE-3：每个 *_selftest.py 都必须登记在本文档里
python checks/regression/run_all_selftest.py           # PRE-3：统一回归入口自身的发现/筛选/汇总
```

**新增汇编块时**：给它写**只有它能产生**的指纹 ✓，并**故意把它移出编译验证一次** ✓ ——
**若闸门仍绿，说明指纹不够独特** ✗（见下方硬规则 ✓）。

### 写汇编时的两个坑（各踩过一次，都值得记）

**① `global_asm!` 在 x86 上默认 Intel 语法** ✓ —— `spinup.rs` 通篇是 Intel ✓。
写成 AT&T（`%eax`）会报 `unknown token in expression` ✗。**改回 Intel 后一次通过** ✓。

**② 破坏性测试之前必须先提交** ✗ —— 有一次做"牙齿测试"时用 `git checkout` 恢复 ✗，
而**被测试的汇编当时还没提交** ✗ → **把自己的工作删掉了** ✗，随后只能重写 ✓。

> **规则：任何会删除/回退/覆盖工作区内容的动作（`git checkout`、删块、清构建产物…）
> 之前，先确认目标内容**已经在提交里** ✓。**未提交的工作没有"恢复"可言** ✗。**

**③ 指纹的唯一性可以用非破坏性办法验证** ✓ —— 不必真的移出编译 ✓：
先确认**别的汇编块里没有那条指令** ✓（例如 `pause` 在 `spinup.rs` 里 0 命中 ✓），
再确认**产物反汇编里有它** ✓。两边都成立，就证明了"这块进了产物" ✓。

### 第 2 步：真机（PRE-2，**5–10 分钟**）

```bash
taskkill /F /T /IM qemu-system-x86_64.exe          # 跑前先清（否则会抢串口）
python checks/liftoff/l5_handoff_check.py --smp 4 --expect-cpus 4 --timeout 420 --dump-serial <file>
# 覆盖矩阵（四格，约 20 分钟）：
python checks/liftoff/l5_handoff_check.py --matrix --expect-cpus auto
```

**`--expect-cpus` 是 S8 判据** ✓ —— 不带它时，"请求 4 核却只报 1 核"**照样 PASS** ✗。

### 第 3 步：推送核实（**每一步提交后都要做**）

```bash
git push origin <branch>
git rev-parse HEAD        # 与下面必须一致
git ls-remote --heads origin <branch>
```

**"推送成功"不能只看 push 的输出** ✗ —— `git push` 在本仓库**间歇性失败** ✓，必须用 `git ls-remote` 比对 ✓。

### 一条硬规则（因一次**假绿**事故而立）

**事故**：`crates/arch/x86_64/src/ap.rs` 的 `global_asm!`、常量与 `stage()` 被**整体夹在
`#[cfg(test)] mod tests` 内部**（模块从第 140 行开始、文件末尾才闭合）。于是**非测试构建里它们
根本不存在** —— 而 `cargo test` 与 UEFI 构建**双双退出 0**。

**为什么没被抓住**：`asm_check.py` 的 `REQUIRED` 只对 **spinup** 提要求 ✓ ——
一个**整块不存在**的汇编，只要**没有任何一条 `REQUIRED` 只有它能产生**，就是**不可见的** ✗。
（当时父代理的"独立复核"也只看了**退出码** ✓，同样没抓住 ✗。）

> **规则：每个 `global_asm!` 块，至少要有一条"只有它能产生"的 `REQUIRED` 条目。**
> 否则该块缺失时闸门**照样全绿** ✗。

**已实测的约束**：release `.efi` **没有符号表** ✓（`llvm-objdump -t` 查不到 `spinup_*` ✗）——
所以判据**只能落在指令上** ✓，不能用"符号是否存在" ✗。

**推论**：新加汇编块时**同时**写下它的**指纹指令** ✓，并**故意把它移出编译验证一次** ✓ ——
若闸门仍绿，说明指纹不够独特 ✗。

三层验收（见 ADR-052），各自独立可跑。**目前没有统一 runner**：每个脚本自带
main() 与退出码，单独调用。是否要一个聚合入口（main.py check 之类）
**待所有者裁定**（A4 结论，见 docs/TODO/liftoff.md）。

| 层 | 脚本 | 作用 |
|---|---|---|
| **PRE-1** | `asm_check.py` | 离线反汇编核对：UEFI `.efi` 里必须出现特定指令与指令序列 |
| **PRE-2** | `l3_gen2_entry_check.py` | QEMU/OVMF 端到端（引导器层）：串口出现 `[liftoff] gen2 up` |
| **PRE-2** | `l5_handoff_check.py` | QEMU/OVMF 端到端（**交接层**）：串口出现 `username:`；`--matrix` 跑 §4.3 四格覆盖矩阵 |
| **PRE-2** | `diag_clients_check.py` | 诊断客户端真机验证：RSP 断点/单步/读内存、HMP 寄存器、`screendump` |
| **PRE-3** | `../regression/check_arch_isolation.py` | 静态隔离：抽象层不得出现实现层依赖；并强制 workspace 成员显式归类 |
| **PRE-3** | `../regression/check_catalog.py` | 本目录清册：每个脚本都必须被 README 登记（防止「存在却无人知道」） |
| **PRE-3** | `mock_impl_check.py` | 确认无人启用的 `impl-mock` 仍能编译（防止静默腐烂） |
| **PRE-3** | `../regression/test_module_leak_selftest.py` | **防假绿**：纯 `pub` 项不得出现在 `#[cfg(test)]` 模块里（判据自带牙齿自检） |
| **PRE-3** | `../regression/config_paths_selftest.py` | **S01**：路径必须派生而非写死；含「换 cwd 结果不变」的行为性断言 |
| **PRE-3** | `../regression/run_smp_selftest.py` | `--smp`/`--no-smp` → QEMU 参数（**E1/S8 判据的输入**） |
| **PRE-3** | `../regression/symbols_selftest.py` | 地址→符号解析离线自检（真机失败诊断的入口，错了会指向错误函数） |
| **PRE-3** | `../regression/elf_image_selftest.py` | ELF64 解析器离线自检（合成 ELF 走公开 API；含**惰性校验**的访问期越界） |
| **PRE-3** | `../regression/iso9660_selftest.py` | ISO9660 解析器离线自检（合成 ISO 走公开 API；坏数据必须报错而非返回伪数据） |
| **PRE-3** | `../regression/diag_selftest.py` | 诊断模块离线自检（RSP 校验和、PPM→PNG、畸形输入拒绝、SerialBuffer 边界、停机包等待） |
| **PRE-3** | `../regression/run_all_selftest.py` | **统一回归入口**的自检：默认不带 QEMU 检查、登记表里的文件必须存在、**空集合不算通过**、超时算失败 |

运行（在 `tools` 目录下）：

```
python checks/liftoff/asm_check.py
python checks/liftoff/l3_gen2_entry_check.py
python checks/liftoff/l5_handoff_check.py             # 单格（约 4 分钟）
python checks/liftoff/l5_handoff_check.py --matrix    # §4.3 四格覆盖矩阵（约 20 分钟）
python checks/liftoff/l5_handoff_check.py --smp 4 --expect-cpus 4   # **S8 判据**：4 核必须报 4
python checks/liftoff/l5_handoff_check.py --matrix --expect-cpus auto   # **S8 矩阵**：每格期望自己的 --smp
python checks/liftoff/diag_clients_check.py
python checks/regression/check_arch_isolation.py
python checks/regression/check_catalog.py
python checks/regression/iso9660_selftest.py
python checks/regression/elf_image_selftest.py
python checks/regression/symbols_selftest.py
python checks/regression/run_smp_selftest.py
python checks/regression/config_paths_selftest.py
python checks/regression/test_module_leak_selftest.py
python checks/liftoff/mock_impl_check.py
python checks/regression/diag_selftest.py
```

注意：`l2_frozen_regs_check.py` 属于早期尝试，**未纳入三层验收**；
面向旧实现的检查已归档到 `legacy/`。
