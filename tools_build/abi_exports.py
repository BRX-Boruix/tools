"""ABI 导出清单的纯逻辑（**与文件系统无关**，故可宿主单测）。

为什么要有这层：版本脚本此前直接用「头文件声明集」（`gen_abi_exports.py` 从 `libc/include/*.h`
机械提取）。但 `-shared` 下 version script 要求**每个 global 都被本库定义**，而声明集里有
`dlopen`/`dlclose`/`dlsym`/`dlerror`——它们由 **rtld** 提供、**libc 不定义** ⇒ `ld.lld` 直接拒绝：

    ld.lld: error: version script assignment of 'global' to symbol 'dlclose' failed: symbol not defined

正确语义：导出面 = **声明集 ∩ 本库实际定义集**。声明集仍是生成器的产物（它回答「我们**打算**
导出什么」），交集才是「**能够**导出什么」。被剔除的名字必须**如实打印**，不静默（S09/S10）。
"""


def parse_version_script(text):
    """取出 version script 里 `global:` 段的符号名（保持原顺序、去重）。"""
    names = []
    seen = set()
    in_global = False
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("global:"):
            in_global = True
            continue
        if t.startswith("local:"):
            in_global = False
            continue
        if in_global and t.endswith(";"):
            name = t[:-1].strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def render_version_script(names):
    """把符号名渲染成 version script（无版本号，`local: *;` 限制导出面）。"""
    out = ["{", "  global:"]
    for n in names:
        out.append("    %s;" % n)
    out += ["  local:", "    *;", "};", ""]
    return "\n".join(out)


def intersect_exports(declared, defined):
    """返回 `(保留, 剔除)`：保留 = 声明集里**本库确实定义**的；剔除 = 声明了但本库不定义的。

    顺序沿用声明集（导出清单的可读性依赖它稳定）。
    """
    kept = [n for n in declared if n in defined]
    removed = [n for n in declared if n not in defined]
    return kept, removed