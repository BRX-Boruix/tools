#!/usr/bin/env python3
"""PRE-3 辅助：确认 `current` 的 mock 实现**仍能编译**。

为什么需要这个检查：`current` 的选择器支持 `impl-x86_64`（默认）与 `impl-mock`，
但**没有任何 crate 启用 `impl-mock`** —— 宿主测试全部走 `impl-x86_64`（其实现里用
`#[cfg(not(target_os = "uefi"))]` 提供宿主桩）。也就是说 **mock 从不参与任何构建**。

无人编译的代码会**静默腐烂**：今天能编过，明天谁改坏了 `Platform` trait 也不会有
任何东西报警 —— 直到真的要用它的那天。这个检查把那一天提前到现在。

**这不是在假装 mock 有用。** mock 是否该保留（还是按 S06 归档）是**所有者决定**；
在决定之前，至少让它保持可用，而不是留一堆看起来在、实际编不过的代码。

退出码：0 = mock 编译通过；1 = 编译失败（打印 cargo 输出尾部）。
"""

import os
import subprocess
import sys

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import liftoff  # noqa: E402

# 只启用 mock、关掉默认的 x86_64 实现 —— 否则两者互斥（`current` 里有 compile_error）。
COMMAND = ["cargo", "check", "-p", "current", "--no-default-features", "--features", "impl-mock"]


def main() -> int:
    result = subprocess.run(
        COMMAND,
        cwd=liftoff.LIFTOFF_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout.decode("utf-8", "replace")
    if result.returncode == 0:
        print("PASS: current 的 impl-mock 仍能编译（" + " ".join(COMMAND) + "）")
        return 0
    print("FAIL: impl-mock 编译失败（退出码 " + str(result.returncode) + "）")
    print("== cargo 输出尾部 ==")
    print(output[-2000:])
    return 1


if __name__ == "__main__":
    sys.exit(main())
