#!/usr/bin/env python3
"""门禁：`confstr(_CS_PATH)` 与 shell 的默认 `PATH` 必须出自**同一个运行期构造点**。

## 历史（为什么这条门禁改过两次）

1. **初版**：两处各写一份字面量，靠门禁核对「逐字节相同」。
   —— 本项初版写的是 `/programs:/bin` 并声称「与 shell/init 的约定一致」，那句话是假的。
2. **第二版**：两侧都由 `tools/abi/constants.json` 生成，门禁核对生成物相等。
   —— 仍然是**编译期常量**，而 `_CS_PATH` 的内容是**部署事实**（卷标 / 有几块盘 / `3p` 在哪块盘上）。
   两侧同错时等式断言永远是绿的（这正是本仓记录过的教训：「等式断言在两侧同错时是瞎的」）。
3. **本版**：两侧都调用 `libsys::search_path()`，在运行期从 `/volumes` 的**真实挂载点**算。
   门禁因此不再比字面量，而是查**接线与残留**：

   - libc 的 `confstr` 的 `_CS_PATH` 分支必须调用 `libsys::search_path()`；
   - shell 的默认 PATH 必须调用同一个函数；
   - **两侧都不得再出现 `/volumes/` 字面量**（那意味着又烧了一个部署事实）；
   - 生成物里**不得再有** `DEFAULT_PATH_C` / `DEFAULT_PATH`（它们已被删除）；
   - 构造点必须**只有一个**：`search_path` 定义在 libsys，且用生成的两个**系统约定**
     （`PROGRAM_DIR` / `THIRD_PARTY_SUBDIR`）拼装，**不引用卷标**。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

LIBC_HAND = os.path.join(ROOT, "libc", "src", "posix_batch7.rs")
SHELL_HAND = os.path.join(ROOT, "shell", "src", "env.rs")
SHELL_CMD = os.path.join(ROOT, "shell", "src", "commands.rs")
LIBSYS_VOL = os.path.join(ROOT, "libsys", "src", "volume.rs")
LIBC_GEN = os.path.join(ROOT, "libc", "src", "abi_generated.rs")


def strip_comments(src):
    """去掉**整行注释**（`//` 开头）。
    为什么必须剥：文档里合法地写着 `/volumes/<卷标>/3p`（解释「为什么不该烧死它」），
    不剥会把**说明**当成**代码**误报。只剥整行注释、不动行尾注释——后者极少出现，
    出现了也该被看见。
    """
    return '\n'.join(
        ln for ln in src.split("\n") if not ln.lstrip().startswith("//")
    )

def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def fail(msg):
    print("[confstr-path] FAIL: " + msg)
    return 1


def main():
    libc_h = read(LIBC_HAND)
    shell_h = read(SHELL_HAND)
    shell_c = read(SHELL_CMD)
    vol = read(LIBSYS_VOL)

    # 1) 接线：两侧都调用同一个运行期构造点。
    if "libsys::search_path()" not in libc_h:
        return fail("libc 的 confstr(_CS_PATH) 未调用 libsys::search_path()")
    if "libsys::search_path()" not in shell_h:
        return fail("shell 的默认 PATH 未调用 libsys::search_path()")
    if "libsys::search_path()" not in shell_c:
        return fail("shell 的 help 文本仍从别处取默认 PATH（应同样调用 libsys::search_path()）")

    # 2) 不得再有烧死的部署事实。
    for path, name in ((LIBC_HAND, "libc/posix_batch7.rs"), (SHELL_HAND, "shell/env.rs")):
        if "/volumes/" in strip_comments(read(path)):
            return fail("%s 里仍有 /volumes/ 字面量（部署事实不该编译期烧死）" % name)

    # 3) 生成物里不得再有默认 PATH 常量（已删除）。
    gen = read(LIBC_GEN)
    for bad in ("DEFAULT_PATH_C", "DEFAULT_PATH"):
        if bad in gen:
            return fail("libc 生成物里仍有 %s（应已删除）" % bad)
    if os.path.exists(os.path.join(ROOT, "shell", "src", "abi_generated.rs")):
        return fail("shell/src/abi_generated.rs 应已删除（它只剩一个默认 PATH 常量）")

    # 4) 构造点唯一，且只用**系统约定**、不引用卷标。
    if vol.count("pub fn search_path()") != 1:
        return fail("libsys 里 search_path 必须**恰好定义一次**（当前 %d 次）" % vol.count("pub fn search_path()"))
    m = re.search(r"pub fn search_path\(\)[^{]*\{(.*?)\n\}", vol, re.S)
    if not m:
        return fail("解析不出 search_path 的函数体")
    body = m.group(1)
    if "PROGRAM_DIR" not in body or "THIRD_PARTY_SUBDIR" not in body:
        return fail("search_path 必须用生成的两个系统约定（PROGRAM_DIR / THIRD_PARTY_SUBDIR）拼装")
    if "DATA_VOLUME_LABEL" in body or "BORUIX_DATA" in body:
        return fail("search_path 里出现了卷标——卷标是部署事实，不能当判据")

    print("[confstr-path] OK: 两侧都调用 libsys::search_path()；无 /volumes/ 字面量；"
          "生成物里无默认 PATH 常量；构造点唯一且不引用卷标")
    return 0


if __name__ == "__main__":
    sys.exit(main())
