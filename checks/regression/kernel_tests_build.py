#!/usr/bin/env python3
"""门禁：**kernel-tests feature 下的内核必须能编译**（登记项：内核自检不在离线套件里）。

为什么需要它（真实缺陷驱动，2026-10-16）：

`kernel/crates/kernel/src/tests.rs` 里的内核自检代码**只在 `--features kernel-tests`
下参与编译**，而默认构建（`python tools/main.py build`）与全部既有离线检查都看不到它。
于是「改了内核 API 但没同步测试」可以潜伏很久：语义忠实性审查登记项⑤ 把
`MountTable::unlink` 加了 `DeleteMode` 参数后，**43 处测试调用点**仍是旧签名，
直到几轮之后跑 `--test`（30 分钟 QEMU）才暴露——而本检查用**编译**就能当场抓住。

退出码：0 = 编译通过；1 = 编译失败（cargo 的错误原样透出）。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _TOOLS)

from tools_build import build  # noqa: E402


def main() -> int:
    # 只做「编译带自检的内核」这一步；不跑 QEMU（那是 --hardware 那一档的事）。
    rc = build._cargo_build_kernel(release=False, use_tests=True)
    if rc == 0:
        print("[kernel-tests-build] OK: kernel-tests feature 下内核编译通过")
        return 0
    print("[kernel-tests-build] FAIL: kernel-tests feature 下内核编译失败（见上方 cargo 输出）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
