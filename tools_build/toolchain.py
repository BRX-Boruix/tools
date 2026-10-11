"""外部工具的解析（跨平台）。

为什么单独成模块：工具名直接交给 `subprocess` 在 Windows 上**不可靠**——
`CreateProcess` 只对**不带点**的名字补 `.exe`。`cargo` 因此正常，而 `ld.lld` 的 `.lld`
被当成扩展名、不再补 `.exe`，于是 `subprocess.run(["ld.lld", ...])` 直接 `FileNotFoundError`
（本机 Python 3.14.7 实测）。这与工具是否存在无关：`shutil.which("ld.lld")` 找得到它。

故：**一律先解析成绝对路径再交给 subprocess**。
"""
import os
import shutil


def resolve_tool(name, env_var=None):
    """把工具名解析成可执行文件的**绝对路径**。

    - `env_var` 给出显式覆盖（如 `BORUIX_LLD`），优先于 PATH 查找；
    - 找不到时抛出带**可操作指引**的 `RuntimeError`，而不是让 subprocess 抛裸 traceback。
    """
    if env_var:
        override = os.environ.get(env_var)
        if override:
            if not os.path.isfile(override):
                raise RuntimeError("%s=%s 指向的文件不存在" % (env_var, override))
            return override
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(
        "找不到工具 %r。把它所在目录加入 PATH，或用 %s 显式指定绝对路径。"
        % (name, env_var or "<env-var>")
    )