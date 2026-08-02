#!/usr/bin/env python3
"""元测试：强制测试_cli_contract.py 遵守 AC-2/AC-4。

契约测试必须通过 subprocess 调用 CLI（sys.executable + loopd/loopd.py 路径），
绝不在源码里直接 `import loopd` / `from loopd import ...`。

运行方式：
    python3 tests/test_cli_meta.py
- 无 import 违例且遵守 subprocess 契约 → EXIT=0
- 任一违例（含被注入 `from loopd import loopd` 这种行）→ EXIT≠0
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "tests" / "test_cli_contract.py"

# AC-2 硬约束：测试不得 import 的模块前缀（loopd 及任何 loopd.*）
VIOLATING_PREFIXES = ("loopd",)


def _direct_loopd_imports(src):
    """用 AST 找出任何 import loopd / from loopd import 的违例。"""
    tree = ast.parse(src, filename=str(CONTRACT))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".", 1)[0] in VIOLATING_PREFIXES:
                    found.append((node.lineno, f"import {a.name}"))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.split(".", 1)[0] in VIOLATING_PREFIXES:
                found.append((node.lineno, f"from {mod} import ..."))
    return found


def main() -> int:
    src = CONTRACT.read_text(encoding="utf-8")

    # AC-4：不得直接 import loopd
    bad = _direct_loopd_imports(src)
    if bad:
        raise AssertionError(
            "test_cli_contract.py 直接 import loopd 违例(AC-4): " + str(bad)
        )

    # AC-2：必须通过 subprocess 调 CLI，且走 sys.executable + loopd.py 路径
    if "subprocess" not in src:
        raise AssertionError("test_cli_contract.py 未使用 subprocess 调用 CLI(AC-2)")
    if "sys.executable" not in src or "loopd.py" not in src:
        raise AssertionError(
            "test_cli_contract.py 未通过 sys.executable + loopd/loopd.py 路径调用 CLI(AC-2)"
        )
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:
        print("META-FAIL:", exc, file=sys.stderr)
        sys.exit(1)
    sys.exit(code)