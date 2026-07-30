"""tests/test_loopd_no_remote_intents.py — 回归测试：relay/filemode/run 远程命令通道已移除（#52/#53）

保证 loopd 不再接受未鉴权的远程命令：
  1. HANDLERS 不含 "run"
  2. relay_thread / filemode_thread / load_intents / h_run 不再作为模块属性存在
  3. main() 启动时不创建 relay/filemode 线程
  4. 往 .loop/IN.json 或 .loop/relay/inbox/ 丢 JSON 不会执行任何 intent
"""
import importlib
import json
import os
import sys
import threading
import time


def _fresh_loopd(tmp_path, monkeypatch):
    """用一个干净的 LOOP_ROOT 重新 import loopd.loopd，避免拿到上一个测试的 _CFG。"""
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("LOOP_ROOT", str(root))
    monkeypatch.setenv("LOOP_WS", str(root))
    monkeypatch.setenv("LOOP_SANDBOX_ID", "test-sbx")
    monkeypatch.setenv("LOOP_ROLE", "impl")
    # 守护进程是 loopd/loopd.py（loopd 是包），必须清掉两个层级才能重载
    sys.modules.pop("loopd.loopd", None)
    sys.modules.pop("loopd", None)
    import pathlib
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root))
    mod = importlib.import_module("loopd.loopd")
    return mod


def test_run_not_in_handlers(tmp_path, monkeypatch):
    """#52 验收：No HANDLERS entry for 'run' after merge."""
    mod = _fresh_loopd(tmp_path, monkeypatch)
    assert "run" not in mod.HANDLERS, "run verb 仍在 HANDLERS 中 —— 远程命令通道未移除干净"


def test_remote_intents_symbols_removed(tmp_path, monkeypatch):
    """#53：relay_thread / filemode_thread / load_intents / h_run 均不应作为模块属性存在。"""
    mod = _fresh_loopd(tmp_path, monkeypatch)
    for name in ("relay_thread", "filemode_thread", "load_intents", "h_run"):
        assert not hasattr(mod, name), f"loopd.{name} 仍存在 —— {name} 应已删除"


def test_relay_dir_not_created_on_cfg(tmp_path, monkeypatch):
    """CFG() 初始化不应再创建 .loop/relay 目录。"""
    mod = _fresh_loopd(tmp_path, monkeypatch)
    mod.CFG()  # 触发初始化
    relay_dir = tmp_path / "root" / ".loop" / "relay"
    assert not relay_dir.exists(), "CFG() 仍创建 .loop/relay 目录 —— RELAY 残留"


def test_main_does_not_start_relay_filemode_threads(tmp_path, monkeypatch):
    """main() 启动的线程集合里不应有 relay_thread / filemode_thread。

    通过 mock threading.Thread 捕获所有 target，断言远程通道线程不在其中。
    main() 末尾是 while True sleep，所以捕获到目标后立刻抛异常退出。
    """
    mod = _fresh_loopd(tmp_path, monkeypatch)
    mod.CFG()  # 初始化全局变量（LOOP 等），main() 裸引用它们

    captured = []
    real_thread = threading.Thread

    class CapturingThread(real_thread):
        def __init__(self, *a, **kw):
            target = kw.get("target") or (a[0] if a else None)
            captured.append(getattr(target, "__name__", str(target)))
            # 不真正 start，避免后台线程污染
            super().__init__(*a, **kw)

    monkeypatch.setattr(threading, "Thread", CapturingThread)
    # 让 main 的 while True sleep 立刻被打断：patch time.sleep 抛 RuntimeError
    def boom(_):
        raise RuntimeError("stop-main-loop")
    monkeypatch.setattr(mod.time, "sleep", boom)

    try:
        mod.main()
    except RuntimeError as e:
        assert "stop-main-loop" in str(e)

    assert "relay_thread" not in captured, f"main 仍启动 relay_thread: {captured}"
    assert "filemode_thread" not in captured, f"main 仍启动 filemode_thread: {captured}"
    # 正常线程应仍在
    assert "heartbeat_thread" in captured, f"heartbeat_thread 未启动: {captured}"
    assert "reaper_thread" in captured, f"reaper_thread 未启动: {captured}"


def test_in_json_drops_do_not_execute(tmp_path, monkeypatch):
    """往 .loop/IN.json 写命令请求，不应触发任何 intent 执行。"""
    mod = _fresh_loopd(tmp_path, monkeypatch)
    mod.CFG()
    loop_dir = tmp_path / "root" / ".loop"

    # 构造一个恶意的 IN.json（file 模式入口）
    (loop_dir / "IN.json").write_text(json.dumps({
        "id": "evil1", "intent": "save", "args": ["pwned"]
    }))

    # 哪怕开了 file 模式也不该有 filemode_thread 处理它
    monkeypatch.setenv("LOOP_IO_MODE", "file")

    # 直接确认：没有 filemode_thread 在跑，IN.json 静静躺着
    assert not hasattr(mod, "filemode_thread")
    # 给一点时间，确认没有其它线程捡起它（heartbeat/autosave/reaper 都不读 IN.json）
    time.sleep(0.3)
    # 没有异常抛出即算通过；额外断言没有 OUT.md 被写（filemode 会写 OUT.md）
    assert not (loop_dir / "OUT.md").exists(), "OUT.md 被写 —— filemode 通道仍在工作"


def test_relay_inbox_drops_do_not_execute(tmp_path, monkeypatch):
    """往 .loop/relay/inbox/ 丢 JSON，不应触发任何 intent 执行。"""
    mod = _fresh_loopd(tmp_path, monkeypatch)
    mod.CFG()
    loop_dir = tmp_path / "root" / ".loop"
    inbox = loop_dir / "relay" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    (inbox / "evil.json").write_text(json.dumps({
        "id": "evil2", "intent": "done", "args": []
    }))

    assert not hasattr(mod, "relay_thread")
    time.sleep(0.3)
    # relay_thread 会把 inbox 文件 rename 到 done/；确认文件还在原地（未被消费）
    assert (inbox / "evil.json").exists(), "relay inbox 文件被消费 —— relay_thread 仍在工作"


def test_help_verb_table_no_run(tmp_path, monkeypatch):
    """VERB_TABLE 不应再列出 run。"""
    mod = _fresh_loopd(tmp_path, monkeypatch)
    assert "run <intent>" not in mod.VERB_TABLE, "VERB_TABLE 仍含 run 条目"
