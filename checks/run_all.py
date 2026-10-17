#!/usr/bin/env python3
"""tools 的**统一回归入口**。

**为什么需要它**：离线检查此前**各自独立、靠手工逐个跑**—— "每个里程碑另加检查"，
**没说谁跑**。于是"某个检查被忘记跑"是常态，而**忘记跑**在结果上与"通过"无法区分。

用法：
    python checks/run_all.py              # 跑**离线**检查（秒级）
    python checks/run_all.py --hardware   # 额外跑需要 QEMU 的检查（当前登记表为空）

退出码 0 = 选中的检查**全部**通过（且**至少有一项真的跑了**）；非 0 = 有失败 / 超时 / 文件缺失。
**空集合不算通过**（"一个都没跑"不是"全绿"）；**全被 SKIP 也不算通过**（同理）。

## 三种结局，严格区分（S09：不把「跑不了」混进「通过」）

- `OK`   —— 真跑了，退出码 0；
- `FAIL` —— 真跑了但非 0，或超时，或登记的文件不存在；
- `SKIP` —— **前置不满足，根本没跑**。`CHECK_PRECONDITIONS` 里声明的前置由**本 runner 自己探针**
  （不依赖子检查的退出码），缺了就打印「缺什么」并跳过。

**为什么前置必须由 runner 探针、而不是把子检查的 exit 2 当 SKIP**：退出码 2 是子检查的**内部约定**，
不同脚本对它的用法并不统一（`headers_syntax.py` 里 2 既表示"缺前置"也表示"没有头文件"）。
把 2 一律当 SKIP 会把真失败吞成"跳过"。故：**探针说 OK 就必须真跑，非 0 一律 FAIL**——
若此时子检查仍以 2 退出，说明它的判定与探针不一致，那是**要暴露的缺陷**，不是要抹平的差异。
"""

import argparse
import os
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(_HERE)

# 需要 QEMU 的检查 —— **显式登记**，不靠文件名猜。当前为空（原登记项已随其子系统归档）。
HARDWARE_CHECKS = ()

# 离线检查（宿主、秒级）。**新增检查必须登记在这里** —— 登记是强制的，
# 不靠"自动发现"：自动发现会让"改名后静默少跑"无法察觉。
OFFLINE_CHECKS = (
    "checks/regression/run_all_selftest.py",
    # 内核自检代码（tests.rs）只在 kernel-tests feature 下参与编译 ⇒ 默认构建与其它
    # 离线检查都看不到它。本项**编译一次带自检的内核**把它纳入门禁：
    # 实测（2026-10-16）登记项⑤ 改了 MountTable::unlink 签名后 43 处测试调用点没跟上，
    # 潜伏数轮才被 30 分钟的 --test 抓到——本项用编译即可当场发现。
    # **代价**：一次 cargo 构建（热 target 下约 1-3 分钟），比同列其它项慢。
    "checks/regression/kernel_tests_build.py",
    # 变异反向验证的「还原」是手工步骤 ⇒ 残留一次就把**被故意改坏**的实现提交进仓库。
    # 实测（2026-10-16）：登记项⑩ 的变异标记就漏还原并被提交，而当时的机内跑测是绿的
    # （绿跑在变异之前）。本项用一次全树扫描杜绝；顺带扫审查脚本的反引号/空字节占位符残留
    # （审查脚本的反引号/空字节占位符）。
    "checks/regression/no_mutation_markers.py",
    "checks/regression/config_paths_selftest.py",
    "checks/regression/iso9660_selftest.py",
    "checks/regression/elf_image_selftest.py",
    "checks/regression/symbols_selftest.py",
    "checks/regression/run_smp_selftest.py",
    "checks/regression/tool_resolution_selftest.py",
    "checks/regression/abi_exports_selftest.py",
    # 发行物门禁：本项**自足**（只读仓库内两处源码做一致性核对），故登记。
    # 系统（Rust）不许知道任何盘的名字/盘上的路径——_CS_PATH 与 shell 默认 PATH 都走
    # PROGRAM_DIR（系统契约）。本项取代了原来的 confstr_path_agrees（它只比两侧字面量，
    # 两侧同错时永远绿）。
    "checks/dist/no_disk_in_system.py",
    # 跨边界镜像常量门禁（syscall 号 / 错误码 / C 头常量 / 路径契约），同样自足。
    "checks/dist/abi_mirrors_agree.py",
    # 跨边界常量的**单一事实源**（tools/abi/constants.json）与两侧生成物的一致性。
    # 此前是"两侧各手写 + 门禁比对数值"；现在数值只有一处，两侧由生成器落盘，
    # 本项负责"生成物没被手改 / 手写 domain·op 与 JSON 一致 / 没有写死的 SYS_* 数值"。
    "abi/generate.py",
    # libc 侧的三项自足审计（纯源码扫描，不需 sysroot/clang）：errno 常量两侧一致、
    # 桩符号清单无新增、C 可见导出都有头文件声明（内部符号须在 TRIAGED_INTERNAL 登记）。
    "../libc/tools/audit_errno_sync.py",
    "../libc/tools/audit_stub_symbols.py",
    "../libc/tools/audit_header_coverage.py",
    # 覆盖面：每个 C 可见导出要么被某个测试组**提到**，要么在 TRIAGED 里写明理由。
    # 它把"审完全部 362 个导出"从一句声称变成可数的清单（名字出现只是下界）。
    "../libc/tools/audit_conformance_coverage.py",
    # 数学核心的宿主对照验证器（独立 rustc 程序）。此前**存在但没人跑**——
    # 它无论超没超都退 0，故本项解析它自己打印的「超 B 档」列表而不是看退出码。
    "checks/dist/math_verify_runs.py",
    # 以下三项**需要前置**（sysroot / clang / llvm-nm），前置在 CHECK_PRECONDITIONS 里声明。
    # 此前它们**一个都没登记**——理由是「登记会让本入口在裸环境里恒红」，而 runner 把
    # 「缺前置（exit 2）」与「失败」都算非 0。**那个理由当时成立、根因在 runner 而非这些检查**：
    # 现在 runner 自己探针前置、缺前置记 SKIP（与 FAIL 严格区分），于是它们可以登记了。
    # 不登记的真实代价（实测过）：libc 的 POSIX 面基线从 25 漂到 13 而**没有任何门禁报警**，
    # 只能靠人记得 install 之后手动跑——「忘记跑」在结果上与「通过」无法区分。
    "../libc/tools/audit_posix_surface.py",   # 需 sysroot + llvm-nm
    "checks/dist/headers_syntax.py",          # 需 sysroot + clang
    "checks/dist/tcc_assets_fresh.py",        # 需 sysroot
)

# 前置声明（**集中一处**，S13）：检查路径 -> 前置名元组。没列在这里的检查 = 无前置。
#
# 只登记**探针能如实回答**的前置。探针返回 (ok, 说明)；说明在 SKIP 时原样打印，
# 让「缺什么、怎么补」当场可见，而不是留一个「跳过」了事。
CHECK_PRECONDITIONS = {
    "../libc/tools/audit_posix_surface.py": ("sysroot", "llvm_nm"),
    "checks/dist/headers_syntax.py": ("sysroot", "clang"),
    "checks/dist/tcc_assets_fresh.py": ("sysroot",),
}


def _probe_sysroot():
    """sysroot 探针：env 指向的目录下必须有 lib/libc.a。

    为什么要求 libc.a 而不只是目录存在：三项检查要的都是**已安装的产物**，空的或半装完的
    sysroot 会让它们以「找不到符号/头文件」的形式报**真失败**，那是误报——前置不满足就该是 SKIP。
    """
    sr = os.environ.get("BORUIX_SYSROOT")
    if not sr:
        return False, "未设 BORUIX_SYSROOT（先 python tools/main.py install --prefix <dir>）"
    libc_a = os.path.join(sr, "lib", "libc.a")
    if not os.path.isfile(libc_a):
        return False, "BORUIX_SYSROOT 下没有 lib/libc.a：" + sr
    return True, sr


def _probe_clang():
    c = os.environ.get("BORUIX_CLANG") or shutil.which("clang")
    if not c:
        return False, "找不到 clang（设 BORUIX_CLANG 或放进 PATH）"
    return True, c


def _probe_llvm_nm():
    n = os.environ.get("BORUIX_NM") or shutil.which("llvm-nm")
    if not n:
        return False, "找不到 llvm-nm（设 BORUIX_NM 或放进 PATH）"
    return True, n


PRECONDITIONS = {
    "sysroot": _probe_sysroot,
    "clang": _probe_clang,
    "llvm_nm": _probe_llvm_nm,
}

# 单个检查的超时。超时**算失败**（不能当成 0）。
CHECK_TIMEOUT_S = 300


def select(hardware: bool) -> list:
    """选中要跑的检查（相对 `tools/` 的路径）。**纯逻辑、宿主可测**。"""
    chosen = list(OFFLINE_CHECKS)
    if hardware:
        chosen.extend(HARDWARE_CHECKS)
    return chosen


# 结局（**三种，严格区分**）：真跑了通过 / 真跑了失败 / 前置不满足没跑。
OK = "ok"
FAIL = "fail"
SKIP = "skip"


def preconditions_of(relative: str) -> tuple:
    """该检查声明的前置名（没声明 => 空元组）。**纯逻辑、宿主可测**。"""
    return CHECK_PRECONDITIONS.get(relative, ())


def missing_preconditions(relative: str, probes=None) -> list:
    """返回**不满足**的前置说明；空列表 = 全部满足。**纯逻辑、宿主可测**。

    `probes` 可注入（测试用），默认取模块级 PRECONDITIONS。
    """
    table = PRECONDITIONS if probes is None else probes
    missing = []
    for name in preconditions_of(relative):
        probe = table.get(name)
        if probe is None:
            missing.append("未定义的前置探针: " + name)
            continue
        ok, detail = probe()
        if not ok:
            missing.append(name + " -> " + detail)
    return missing


def summarize(results) -> int:
    """把 [(路径, 结局)] 汇总成进程退出码。**纯逻辑、宿主可测**。

    退出码 0 的条件：**没有 FAIL**，且**至少一项真的跑了（OK）**。
    - 空集合 -> 非 0（"一个都没跑"不是"全绿"）；
    - 全 SKIP -> 非 0（同理：前置全不满足不等于通过）。
    """
    if not results:
        return 1
    if any(outcome == FAIL for _, outcome in results):
        return 1
    if not any(outcome == OK for _, outcome in results):
        return 1
    return 0


def run_one(relative: str):
    """跑一个检查，返回 (结局, 说明)。

    前置不满足 => (SKIP, 缺什么)，**不启动子进程**——启动一个明知会失败的程序，
    再把它失败的结果算成"失败"或"通过"，两种都是错的。
    """
    full = os.path.join(_TOOLS_DIR, relative)
    if not os.path.isfile(full):
        return FAIL, "登记的文件不存在: " + full
    missing = missing_preconditions(relative)
    if missing:
        return SKIP, "缺前置 —— " + "；".join(missing)
    try:
        proc = subprocess.run(
            [sys.executable, full],
            cwd=_TOOLS_DIR,
            timeout=CHECK_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return FAIL, "超时（%d 秒）" % CHECK_TIMEOUT_S
    if proc.returncode == 0:
        return OK, ""
    if proc.returncode == 2:
        return FAIL, ("exit=2 —— 探针认为前置齐全，子检查却报缺前置；两者判定不一致，"
                      "按失败处理（不把「跑不了」混进「通过」）")
    return FAIL, "exit=%d" % proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="tools 统一回归入口")
    parser.add_argument("--hardware", action="store_true",
                        help="额外跑需要 QEMU 的检查（当前登记表为空）")
    args = parser.parse_args()

    chosen = select(args.hardware)
    results = []
    for relative in chosen:
        print("== " + relative)
        outcome, detail = run_one(relative)
        print("   " + outcome.upper() + (": " + detail if detail else ""))
        results.append((relative, outcome))

    failed = [p for p, o in results if o == FAIL]
    skipped = [p for p, o in results if o == SKIP]
    print("")
    print("共 %d 项：跑 %d 项、跳过 %d 项、失败 %d 项"
          % (len(results), len(results) - len(skipped), len(skipped), len(failed)))
    for p in skipped:
        print("  SKIP: " + p)
    for p in failed:
        print("  FAIL: " + p)
    return summarize(results)


if __name__ == "__main__":
    sys.exit(main())
