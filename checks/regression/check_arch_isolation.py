#!/usr/bin/env python3
"""PRE-3: 静态检查——中立层不得依赖具体实现（ADR-050 / ADR-007）。

规则：中立层 crate 的源码与清单不得出现对具体实现的依赖：
`use efi::` / `use x86_64::` / `extern crate efi` / 清单里的 `efi = ...`、`x86_64 = ...`。

**为什么需要「成员归类完备性」断言。** 本检查最初用一份手维护的目录清单，那是
**fail-open** 的：新增一个中立层 crate 而忘记加进清单，它会被**静默跳过**，检查照样
报绿 —— 从「没有检查」变成「检查了但漏了」，而后者更危险，因为它给人虚假的信心。
现在改为：从 `Cargo.toml` **枚举全部 workspace 成员**，要求每个成员被显式归入
中立 / 选择器 / 实现三类之一；出现未归类成员即失败，逼着新增 crate 时做一次分类决定。

用法：check_arch_isolation.py [--root <仓库根>]（默认按脚本位置推断 liftoff 仓库）
退出码：0 = 干净且成员归类完备；1 = 有违规或未归类成员（逐条打印）。
"""

import argparse
import re
import sys
import tomllib
from pathlib import Path

# 中立层（抽象）：不得依赖任何具体实现。扫描范围是各 crate 的 `src/` 与 `Cargo.toml`
# —— 用 `src/` 而不是整个 crate 目录，天然排除嵌套的选择器（如 `crates/firmware/current/src`）。
NEUTRAL_CRATES = [
    "crates/firmware",
    "crates/arch/arch",
    "crates/mm",
    "crates/fs",
    "crates/driver",
    "crates/loader",
    "crates/utils",
    "crates/protocol/limine",
]

# 选择器层（ADR-050）：职责就是「把具体实现接到抽象上」，**本来就该**依赖实现。
SELECTOR_CRATES = [
    "crates/firmware/current",
    "crates/arch/current",
]

# 实现层与入口层：允许依赖实现。
IMPLEMENTATION_CRATES = [
    "crates/efi",
    "crates/arch/x86_64",
    "crates/boot",
]

FORBIDDEN = [
    (re.compile(r"\buse\s+efi\s*::"), "use efi::（中立层不得依赖 UEFI 实现）"),
    (re.compile(r"\buse\s+x86_64\s*::"), "use x86_64::（中立层不得依赖架构实现）"),
    (re.compile(r"\bextern\s+crate\s+efi\b"), "extern crate efi"),
    (re.compile(r"\bextern\s+crate\s+x86_64\b"), "extern crate x86_64"),
    (re.compile(r"^\s*efi\s*="), "Cargo.toml 依赖 efi"),
    (re.compile(r"^\s*x86_64\s*="), "Cargo.toml 依赖 x86_64"),
]


def workspace_members(root: Path) -> list:
    """从根 `Cargo.toml` 读 `[workspace] members`。读不到就抛错，不返回空表。

    返回空表会让完备性断言变成「0 个成员，全部已归类」的假绿。
    """
    manifest = root / "Cargo.toml"
    if not manifest.is_file():
        raise FileNotFoundError("找不到 " + str(manifest))
    with manifest.open("rb") as handle:
        data = tomllib.load(handle)
    members = data.get("workspace", {}).get("members")
    if not members:
        raise ValueError(str(manifest) + " 里没有 [workspace] members —— 完备性断言无法进行")
    return [str(item) for item in members]


def scan_targets(root: Path) -> list:
    """中立层的扫描目标：各中立 crate 的 `Cargo.toml` 与 `src/` 下的全部文件。"""
    targets = []
    for crate in NEUTRAL_CRATES:
        manifest = root / crate / "Cargo.toml"
        if manifest.is_file():
            targets.append(manifest)
        src = root / crate / "src"
        if src.is_dir():
            targets.extend(sorted(p for p in src.rglob("*") if p.is_file()))
    return targets


def scan(root: Path) -> list:
    problems = []
    for path in scan_targets(root):
        if path.suffix not in (".rs", ".toml") or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            for pattern, why in FORBIDDEN:
                if pattern.search(line):
                    problems.append(
                        "%s:%d: %s  <- %s"
                        % (path.relative_to(root), number, line.strip(), why)
                    )
    return problems


def unclassified_members(root: Path) -> list:
    """列出既不在中立、也不在选择器、也不在实现清单里的 workspace 成员。"""
    classified = set(NEUTRAL_CRATES) | set(SELECTOR_CRATES) | set(IMPLEMENTATION_CRATES)
    return [member for member in workspace_members(root) if member not in classified]


def main() -> int:
    parser = argparse.ArgumentParser()
    default_root = Path(__file__).resolve().parents[3] / "liftoff"
    parser.add_argument("--root", default=str(default_root))
    args = parser.parse_args()
    root = Path(args.root)
    if not root.is_dir():
        print("FAIL: 仓库根不存在: " + str(root))
        return 1

    # 先做完备性检查：漏归类比漏扫更危险，所以先报它。
    try:
        missing = unclassified_members(root)
    except (FileNotFoundError, ValueError, tomllib.TOMLDecodeError) as exc:
        print("FAIL: 无法确定 workspace 成员（完备性断言无法进行）: " + str(exc))
        return 1
    if missing:
        for member in missing:
            print("  UNCLASSIFIED " + member)
        print(
            "FAIL: " + str(len(missing)) + " 个 workspace 成员未归类 —— "
            "新增 crate 必须显式归入中立 / 选择器 / 实现三类之一（否则它会被静默漏扫）"
        )
        return 1

    problems = scan(root)
    if problems:
        for problem in problems:
            print("  VIOLATION " + problem)
        print("FAIL: 中立层出现 " + str(len(problems)) + " 处实现依赖")
        return 1

    print(
        "PASS: 中立层无实现依赖（扫描 " + str(len(NEUTRAL_CRATES)) + " 个 crate），"
        "且 " + str(len(workspace_members(root))) + " 个 workspace 成员全部已归类"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
