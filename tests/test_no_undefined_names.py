"""未定义名回归测试。

起因：loopd.py 里三处 f-string 写成 `E.get("LOOP_ORG", Cloudbird-Software)`，
少了引号。它**语法合法**（被解析成 `Cloudbird - Software` 的减法），所以
`py_compile` 与语法检查全都放行，只有真正走到那一行才炸 NameError。
这正是 loop 仓此前"零 PR 门禁"漏出去的那一类 bug（对应审查裁决 F-D）。

本测试是一个极简的未定义名分析器：收集模块内所有被绑定的名字（import、赋值、
函数/类定义、参数、for/with/except/comprehension 目标、global/nonlocal 声明）
加上内建名，然后断言不存在读取了这些集合之外的名字。

它不追求 pyflakes 的完备性，只求把"少写引号的裸名"这一类挡住——按 ADR-006，
被确认的缺陷应当固化为不依赖任何 LLM 的确定性检查器，这就是其中一条。
"""
import ast
import builtins
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

SCAN_DIRS = ["conductor", "loopd", "gates", "seam_a", "lenses"]


def _python_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for f in sorted(base.rglob("*.py")):
            yield f


class _BindingCollector(ast.NodeVisitor):
    """收集模块中任意位置绑定过的名字（不区分作用域，故意保守）。"""

    def __init__(self):
        self.bound = set()

    def _bind_target(self, node):
        if isinstance(node, ast.Name):
            self.bound.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                self._bind_target(elt)
        elif isinstance(node, ast.Starred):
            self._bind_target(node.value)

    def visit_Import(self, node):
        for a in node.names:
            self.bound.add((a.asname or a.name).split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for a in node.names:
            self.bound.add(a.asname or a.name)
        self.generic_visit(node)

    def visit_Assign(self, node):
        for t in node.targets:
            self._bind_target(t)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self._bind_target(node.target)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        self._bind_target(node.target)
        self.generic_visit(node)

    def visit_NamedExpr(self, node):
        self._bind_target(node.target)
        self.generic_visit(node)

    def visit_For(self, node):
        self._bind_target(node.target)
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_comprehension(self, node):
        self._bind_target(node.target)
        self.generic_visit(node)

    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars is not None:
                self._bind_target(item.optional_vars)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_ExceptHandler(self, node):
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node):
        self.bound.update(node.names)
        self.generic_visit(node)

    def visit_Nonlocal(self, node):
        self.bound.update(node.names)
        self.generic_visit(node)

    def _bind_args(self, args):
        for a in (
            list(args.posonlyargs)
            + list(args.args)
            + list(args.kwonlyargs)
            + ([args.vararg] if args.vararg else [])
            + ([args.kwarg] if args.kwarg else [])
        ):
            self.bound.add(a.arg)

    def visit_FunctionDef(self, node):
        self.bound.add(node.name)
        self._bind_args(node.args)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.bound.add(node.name)
        self.generic_visit(node)

    def visit_Lambda(self, node):
        self._bind_args(node.args)
        self.generic_visit(node)


def _undefined_names(tree):
    collector = _BindingCollector()
    collector.visit(tree)
    known = collector.bound | set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in known:
                bad.append((node.id, node.lineno))
    return bad


@pytest.mark.parametrize("path", list(_python_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_undefined_names(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bad = _undefined_names(tree)
    assert not bad, (
        f"{path.relative_to(ROOT)} 引用了未定义的名字（很可能是漏写引号的裸名）: "
        + ", ".join(f"{name}@L{line}" for name, line in bad)
    )


def test_detector_catches_the_original_bug():
    """负向自证：本检查器必须能抓住 loopd.py 当初那个写法。"""
    src = 'E = {}\nx = f\'user.email=loop@{E.get("LOOP_ORG", Cloudbird-Software)}.invalid\'\n'
    bad = _undefined_names(ast.parse(src))
    names = {n for n, _ in bad}
    assert "Cloudbird" in names and "Software" in names, bad


def test_detector_accepts_the_fixed_form():
    src = 'E = {}\nx = f\'user.email=loop@{E.get("LOOP_ORG", "Cloudbird-Software")}.invalid\'\n'
    assert _undefined_names(ast.parse(src)) == []
