#!/usr/bin/env python3
"""门禁：源码树里不得残留**变异标记**（`MUTATION`）或审查占位符（`@BT@` / `@Z@`）。

为什么需要它（真实事故驱动，2026-10-16）：

语义忠实性审查的每一项都做「**变异反向验证**」——临时把实现改坏、跑一遍证明门禁会红、
再还原。**还原这一步是手工的**。登记项⑩ 那次：`mut_sigproc.py restore` 打印了「已还原」
与正确的哈希，但工作树里**仍留着** `// MUTATION: 退回旧行为…` 那行；随后的提交把它
一起提交了 ⇒ 仓库里躺着一份**被故意改坏**的实现（`fork` 不再继承信号处置），
而**当时的机内跑测是绿的**（绿跑发生在变异之前）。

更早还有一类同类事故：审查脚本用 `@BT@`/`@Z@` 占位反引号与空字节，漏还原会写坏源码。
两类都是「用一次全树扫描就能杜绝」的，故立此门禁。

扫描范围：各源码仓（kernel/libc/libsys/shell/init/login/tools）的源文件；
**不含 docs**——审查报告与补丁里合法地记录着这些词。

退出码：0 = 干净；1 = 发现残留（逐个打印 path:line）。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))

# 源码仓（docs 故意不在内：报告与补丁里合法地写着这些词）。
_TREES = ("kernel", "libc", "libsys", "shell", "init", "login", "tools")
_EXTS = (".rs", ".c", ".h", ".json", ".py", ".ps1")
_SKIP_DIRS = {"target", ".git", "__pycache__", "_build", "node_modules"}
_PATTERNS = ("MUTATION", "@BT@", "@Z@")


def main() -> int:
    hits = []
    for tree in _TREES:
        base = os.path.join(_ROOT, tree)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in filenames:
                if not fn.endswith(_EXTS):
                    continue
                p = os.path.join(dirpath, fn)
                # 本文件自身**合法地**写着这些模式（它要检测它们）⇒ 跳过自指。
                if os.path.abspath(p) == os.path.abspath(__file__):
                    continue
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            for pat in _PATTERNS:
                                if pat in line:
                                    hits.append((p, i, pat, line.strip()[:100]))
                except OSError:
                    continue
    if not hits:
        print("[no-mutation-markers] OK: 源码树里没有变异标记/占位符残留")
        return 0
    for p, i, pat, line in hits:
        print("%s:%d: [%s] %s" % (p, i, pat, line))
    print("[no-mutation-markers] FAIL: 共 %d 处残留（见上）" % len(hits))
    return 1


if __name__ == "__main__":
    sys.exit(main())
