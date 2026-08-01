#!/usr/bin/env python3
"""W0-5 digest 与 liveness 单测（Copilot review 建议：补 generate_digest 覆盖）。

覆盖：
  TC-LIV-1  _load_liveness_config 正常解析：ticks 列表含 name + expect_hours
  TC-LIV-2  _load_liveness_config 文件缺失：返回 []
  TC-LIV-3  _load_liveness_config 非整数 expect_hours：容错保留默认 0（ValueError 分支）
  TC-DIG-1  generate_digest 模板缺失：打印提示且不抛异常（优雅降级）
  TC-DIG-2  generate_digest 正常渲染：占位符全部被替换，输出文件含四问标题
  TC-DIG-3  generate_digest gh 失败容错：_gather_* 降级路径不中断渲染

运行：python tests/test_w0_5_digest.py
"""
import os, sys, tempfile, pathlib, importlib, shutil

HERE = pathlib.Path(__file__).resolve().parent
WORKSPACE = HERE.parent


def _setup_env():
    """为单个测试搭建隔离环境，返回 (tmp_dir, tick_module, cleanup_fn)。

    Copilot review：原实现把 os.environ / sys.path 突变放在模块级，
    pytest 收集时即生效，会泄漏到其他测试造成顺序依赖。
    改为 per-test setup，每次调用都创建全新临时目录、保存/恢复环境变量。
    Copilot round-7 review：reload 会改变共享的 conductor.tick 模块对象，
    影响其他测试模块的模块级常量。cleanup 里恢复环境变量后重新 reload tick，
    使其回到原始 LOOP_ROOT / POLICY 绑定（消除跨测试污染）。
    """
    saved_env = os.environ.copy()
    saved_path = sys.path[:]
    # 记录 conductor.tick 是否已被其他测试 import，cleanup 时据此决定是否 restore
    tick_was_loaded = "conductor.tick" in sys.modules

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="w05-digest-test-"))
    os.environ["LOOP_ROOT"] = str(tmp)
    os.environ["LOOP_POLICY"] = str(tmp / "policy.yml")
    os.environ["GH_TOKEN"] = "dummy"
    os.environ.setdefault("LOOP_ORG", "test-org")
    os.environ.setdefault("LOOP_REPO", "test-repo")

    if str(WORKSPACE) not in sys.path:
        sys.path.insert(0, str(WORKSPACE))

    (tmp / "policy.yml").write_text("freeze:\n  all: false\n")

    # 懒加载 tick 模块，确保它在正确的环境变量下被 import
    if "conductor.tick" in sys.modules:
        tick_module = importlib.reload(sys.modules["conductor.tick"])
    else:
        from conductor import tick as tick_module

    def cleanup():
        # 先恢复环境变量，再 reload tick 使其绑定回原始 LOOP_ROOT / POLICY
        os.environ.clear()
        os.environ.update(saved_env)
        sys.path[:] = saved_path
        if tick_was_loaded and "conductor.tick" in sys.modules:
            importlib.reload(sys.modules["conductor.tick"])
        if tmp.exists():
            shutil.rmtree(str(tmp), ignore_errors=True)

    return tmp, tick_module, cleanup


def _reload_tick_with_root(tick_module, root):
    """重新 import tick 使其 LOOP_ROOT 指向 root（模块级常量在 import 时绑定）。

    reload 前显式更新 LOOP_ROOT 环境变量，确保 tick.resolve_loop_root() 在
    重新加载时读到新值（Copilot review：原实现未用 root 参数，docstring 与行为不符）。
    """
    os.environ["LOOP_ROOT"] = str(root)
    return importlib.reload(tick_module)


def setup_liveness(root, ticks):
    """在 root/.loop/liveness.yml 写给定 ticks 列表。"""
    lp = root / ".loop" / "liveness.yml"
    lp.parent.mkdir(parents=True, exist_ok=True)
    lines = ["ticks:"]
    for t in ticks:
        lines.append(f"  - name: {t['name']}")
        lines.append(f"    expect_hours: {t['expect_hours']}")
    lp.write_text("\n".join(lines) + "\n")


def setup_template(root, body):
    """在 root/.loop/templates/human-todo.md 写模板。"""
    p = root / ".loop" / "templates" / "human-todo.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


# ==================================================================
# TC-LIV-1: 正常解析
# ==================================================================
def test_liveness_normal_parse():
    tmp, T, cleanup = _setup_env()
    try:
        T = _reload_tick_with_root(T, tmp)
        setup_liveness(tmp, [
            {"name": "conductor", "expect_hours": 1},
            {"name": "audit", "expect_hours": 30},
        ])
        ticks = T._load_liveness_config()
        assert len(ticks) == 2, f"expected 2 ticks, got {len(ticks)}: {ticks}"
        assert ticks[0]["name"] == "conductor" and ticks[0]["expect_hours"] == 1
        assert ticks[1]["name"] == "audit" and ticks[1]["expect_hours"] == 30
        print("TC-LIV-1 PASS: normal parse returns 2 ticks with correct fields")
    finally:
        cleanup()


# ==================================================================
# TC-LIV-2: 文件缺失返回 []
# ==================================================================
def test_liveness_missing_file():
    tmp, T, cleanup = _setup_env()
    try:
        T = _reload_tick_with_root(T, tmp)
        lp = tmp / ".loop" / "liveness.yml"
        if lp.exists():
            lp.unlink()
        ticks = T._load_liveness_config()
        assert ticks == [], f"expected [] for missing file, got {ticks}"
        print("TC-LIV-2 PASS: missing file returns []")
    finally:
        cleanup()


# ==================================================================
# TC-LIV-3: 非整数 expect_hours 容错
#   - PyYAML 可用：yaml.safe_load 把 "abc" 解析为字符串，原样返回（不抛）
#   - PyYAML 不可用（fallback 简易解析）：int("abc") 抛 ValueError → 保留默认 0
#   两种路径都不应中断，且 good 项始终正确解析为 5。
# ==================================================================
def test_liveness_non_integer_expect_hours():
    tmp, T, cleanup = _setup_env()
    try:
        T = _reload_tick_with_root(T, tmp)
        lp = tmp / ".loop" / "liveness.yml"
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text("ticks:\n  - name: bad\n    expect_hours: abc\n  - name: good\n    expect_hours: 5\n")
        ticks = T._load_liveness_config()
        assert len(ticks) == 2, f"expected 2 ticks, got {len(ticks)}: {ticks}"
        good = [t for t in ticks if t["name"] == "good"][0]
        assert good["expect_hours"] == 5, f"good expect_hours should be 5, got {good['expect_hours']}"
        # bad 项：PyYAML 路径返回字符串 "abc"，fallback 路径返回 0；两者都不抛异常即可
        bad = [t for t in ticks if t["name"] == "bad"][0]
        assert bad["expect_hours"] in (0, "abc"), f"bad expect_hours should be 0 or 'abc', got {bad['expect_hours']}"
        print(f"TC-LIV-3 PASS: non-integer expect_hours tolerated (bad={bad['expect_hours']!r}, good=5)")
    finally:
        cleanup()


# ==================================================================
# TC-LIV-4: _gather_degradations 遇到非整数 expect_hours 不 crash
#   Copilot review: expect <= 0 若 expect 是字符串会 TypeError 中断 digest。
#   修复后强制 int() 转换，转换失败按 0 跳过该项。
# ==================================================================
def test_degradations_non_integer_expect_no_crash():
    tmp, T, cleanup = _setup_env()
    try:
        T = _reload_tick_with_root(T, tmp)
        lp = tmp / ".loop" / "liveness.yml"
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text("ticks:\n  - name: bad\n    expect_hours: abc\n")
        setup_template(tmp, "{{degradations}}")
        # monkeypatch gh 返回空 run 列表，聚焦验证类型守卫而非网络
        orig_gh = T.gh
        T.gh = lambda *a, **kw: type("R", (), {"stdout": "[]", "stderr": "", "returncode": 0})()
        try:
            T.generate_digest()  # 不应抛 TypeError
        finally:
            T.gh = orig_gh
        out = tmp / ".loop" / "HUMAN-TODO.md"
        assert out.exists(), "digest should still be written despite non-integer expect_hours"
        print("TC-LIV-4 PASS: non-integer expect_hours in degradations does not crash digest")
    finally:
        cleanup()


# ==================================================================
# TC-DIG-1: 模板缺失 → 优雅降级（打印提示，不抛异常）
# ==================================================================
def test_digest_template_missing():
    tmp, T, cleanup = _setup_env()
    try:
        T = _reload_tick_with_root(T, tmp)
        # 确保模板不存在
        tpl = tmp / ".loop" / "templates" / "human-todo.md"
        if tpl.exists():
            tpl.unlink()
        # 清掉前序测试可能残留的输出文件，避免误判
        out = tmp / ".loop" / "HUMAN-TODO.md"
        if out.exists():
            out.unlink()
        # 不应抛异常，且不应生成输出文件
        T.generate_digest()
        assert not out.exists(), "HUMAN-TODO.md should NOT be written when template missing"
        print("TC-DIG-1 PASS: missing template → graceful degradation, no exception, no output file")
    finally:
        cleanup()


# ==================================================================
# TC-DIG-2: 正常渲染 → 占位符全部替换
# ==================================================================
def test_digest_normal_render():
    tmp, T, cleanup = _setup_env()
    try:
        T = _reload_tick_with_root(T, tmp)
        # 清掉 liveness.yml 避免 _gather_degradations 里 age_h > expect 类型比较失败
        lp = tmp / ".loop" / "liveness.yml"
        if lp.exists():
            lp.unlink()
        template = """# HUMAN-TODO @ {{generated_at}}

## 1. 卡在我这的
{{blocked_on_human}}

## 2. 昨天放行的
{{released_yesterday}}

## 3. 什么退化了
{{degradations}}

## 4. 花了多少
{{cost}}

## liveness
{{liveness_table}}
"""
        setup_template(tmp, template)
        # monkeypatch gh 让 _gather_* 走降级路径（避免真实网络调用）
        orig_gh = T.gh
        T.gh = lambda *a, **kw: type("R", (), {"stdout": "[]", "stderr": "", "returncode": 0})()
        try:
            T.generate_digest()
        finally:
            T.gh = orig_gh
        out = tmp / ".loop" / "HUMAN-TODO.md"
        assert out.exists(), "HUMAN-TODO.md should be written"
        content = out.read_text(encoding="utf-8")
        # 占位符全部被替换（不应残留 {{...}}）
        assert "{{" not in content and "}}" not in content, f"unreplaced placeholders remain: {content}"
        # 含四问标题
        assert "卡在我这的" in content
        assert "昨天放行的" in content
        assert "什么退化了" in content
        assert "花了多少" in content
        print("TC-DIG-2 PASS: normal render replaces all placeholders, four questions present")
    finally:
        cleanup()


# ==================================================================
# TC-DIG-3: gh 失败容错（_gather_* 降级不中断渲染）
# ==================================================================
def test_digest_gh_failure_tolerant():
    tmp, T, cleanup = _setup_env()
    try:
        T = _reload_tick_with_root(T, tmp)
        setup_template(tmp, "{{blocked_on_human}}\n{{degradations}}")
        # monkeypatch gh 抛异常模拟调用失败
        orig_gh = T.gh
        def boom(*a, **kw):
            raise RuntimeError("network down")
        T.gh = boom
        try:
            T.generate_digest()
        finally:
            T.gh = orig_gh
        out = tmp / ".loop" / "HUMAN-TODO.md"
        assert out.exists(), "HUMAN-TODO.md should still be written even if gh fails"
        print("TC-DIG-3 PASS: gh failure tolerated, digest still rendered")
    finally:
        cleanup()


if __name__ == "__main__":
    tests = [
        test_liveness_normal_parse,
        test_liveness_missing_file,
        test_liveness_non_integer_expect_hours,
        test_degradations_non_integer_expect_no_crash,
        test_digest_template_missing,
        test_digest_normal_render,
        test_digest_gh_failure_tolerant,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"{t.__name__} FAIL: {type(e).__name__}: {e}")
    print(f"\n{'='*40}\n{len(tests)-failed}/{len(tests)} passed" + (f", {failed} FAILED" if failed else ""))
    sys.exit(1 if failed else 0)
