#!/usr/bin/env python3
"""`checks/run_all.py` 的自检 —— 宿主、离线、**不碰 QEMU**。

测的是**发现 / 筛选 / 前置判定 / 汇总**这四件纯逻辑，不是"被跑的那些检查能不能过"
（那是它们自己的事）。

**为什么必须有它**：一个"统一入口"如果自己没被测，它可能"一个检查都没跑"却退出 0 ——
那就把"忘记跑"变成了"看起来通过"，比没有入口更坏。

**本轮新增（前置机制）**：SKIP 必须与 FAIL 严格区分，且三条不变量要被钉住——
① 全 SKIP 不算通过；② 声明了却找不到探针的前置名必须报出来（不许静默通过）；
③ 前置声明与登记表、探针表三者不许有孤儿项。
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(os.path.dirname(_HERE))
RUN_ALL = os.path.join(_TOOLS_DIR, "checks", "run_all.py")

_failures = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   " + name)
    else:
        print("  FAIL " + name + (" :: " + detail if detail else ""))
        _failures.append(name)


def load():
    spec = importlib.util.spec_from_file_location("run_all", RUN_ALL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    if not os.path.isfile(RUN_ALL):
        print("FAIL: 找不到 " + RUN_ALL)
        return 1
    m = load()

    # 1) 默认**不带**硬件检查；`--hardware` 才带上。
    offline = m.select(False)
    with_hw = m.select(True)
    check("默认选择里没有需要 QEMU 的检查", not (set(offline) & set(m.HARDWARE_CHECKS)),
          str(set(offline) & set(m.HARDWARE_CHECKS)))
    check("--hardware 会带上硬件检查",
          set(with_hw) == set(offline) | set(m.HARDWARE_CHECKS))
    check("默认选择非空", len(offline) > 0, "空 = 一个都不跑，等于没有入口")

    # 2) 登记表里的每个路径**都必须真实存在** —— 改名/删文件后不能静默少跑。
    missing = [p for p in with_hw if not os.path.isfile(os.path.join(_TOOLS_DIR, p))]
    check("登记表里每个检查文件都存在", not missing, "缺失: " + str(missing))

    # 3) 汇总：**空集合不能算通过**；**全 SKIP 也不能算通过**。
    check("空结果集 -> 非 0", m.summarize([]) != 0)
    check("全通过 -> 0", m.summarize([("a", m.OK), ("b", m.OK)]) == 0)
    check("有一个失败 -> 非 0", m.summarize([("a", m.OK), ("b", m.FAIL)]) != 0)
    check("全 SKIP -> 非 0（前置全不满足不等于通过）",
          m.summarize([("a", m.SKIP), ("b", m.SKIP)]) != 0)
    check("有 OK 有 SKIP 无 FAIL -> 0（跳过的不影响已跑项）",
          m.summarize([("a", m.OK), ("b", m.SKIP)]) == 0)

    # 4) 前置判定：注入探针，验证 SKIP 路径**真的会短路**。
    gated = "../libc/tools/audit_posix_surface.py"
    check("有前置声明的检查能被查到", len(m.preconditions_of(gated)) > 0)
    check("没声明的检查前置为空", m.preconditions_of("checks/regression/iso9660_selftest.py") == ())

    def always_ok():
        return True, "ok"

    def always_bad():
        return False, "故意缺"

    probes_ok = {name: always_ok for name in m.PRECONDITIONS}
    probes_bad = {name: always_bad for name in m.PRECONDITIONS}
    check("前置齐全 -> 无缺失项", m.missing_preconditions(gated, probes_ok) == [])
    check("前置缺失 -> 逐条报出（含说明）",
          len(m.missing_preconditions(gated, probes_bad)) == len(m.preconditions_of(gated)))

    # 5) 声明了却**没有探针**的前置名：必须报出来，不许静默通过。
    probes_partial = {k: v for k, v in probes_ok.items() if k != "llvm_nm"}
    bad = m.missing_preconditions(gated, probes_partial)
    check("未定义探针的前置名 -> 报缺失（不静默通过）",
          any("未定义的前置探针" in s for s in bad), str(bad))

    # 6) 三张表之间不许有孤儿：声明里的名字都要有探针，声明里的路径都要在登记表里。
    known = set(m.PRECONDITIONS)
    orphan_names = sorted({n for names in m.CHECK_PRECONDITIONS.values() for n in names} - known)
    check("前置声明里的名字都有探针", not orphan_names, str(orphan_names))
    orphan_paths = sorted(set(m.CHECK_PRECONDITIONS) - set(m.OFFLINE_CHECKS))
    check("前置声明里的路径都在登记表里", not orphan_paths, str(orphan_paths))

    # 7) run_one：文件不存在 => FAIL（不是 None、更不是 OK）。
    outcome, detail = m.run_one("checks/regression/__no_such_check__.py")
    check("不存在的检查 -> FAIL", outcome == m.FAIL and "不存在" in detail, detail)

    print("")
    if _failures:
        print("FAIL: " + str(len(_failures)) + " 项: " + ", ".join(_failures))
        return 1
    print("PASS: run_all 自检")
    return 0


if __name__ == "__main__":
    sys.exit(main())
