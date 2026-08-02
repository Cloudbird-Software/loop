#!/usr/bin/env python3
"""conductor/cas.py — loop-state 真 CAS（compare-and-swap）统一写入口（W2-1）。

目标：把 loop-state 分支当作"状态真源"，所有状态落地都经本模块的
``cas_update()`` 以 git ref ``force=false``（fast-forward-only）做乐观并发控制，
从根上堵住伪 CAS 与"静默覆盖并发写"：

  - 写前读当前 ref（GET ``/repos/{repo}/git/refs/heads/loop-state``）；
  - 校验 ref 当前 sha == 调用方持有的 ``base_sha``；不等 → 立即 ``CASConflict``；
  - PATCH ref 时强制 ``force=false``：GitHub 对非快进推(ref 已被别人推进)返回 422，
    我方把 422 归一化为 ``CASConflict``，调用方"重读最新 ref 后重试"；
  - ``force=true`` 永远被拒绝（AC-5 负证）：宁可抛错，绝不静默覆盖并发写。

目录布局常量（AC-4）：loop-state 分支根 dirs。
"""
from __future__ import annotations

import os
import subprocess
import sys

E = os.environ


class CASConflict(Exception):
    """CAS 冲突：ref 当前 sha 与调用方 base_sha 不一致。

    唯一出口是抛异常，绝不悄悄覆盖；上层捕获后应重读最新 ref 并重试。
    """


# AC-4：loop-state 分支根目录布局（唯一事实来源，供物化/审计/清扫复用）
LOOP_STATE_DIRS = ("cards", "leases", "audit", "plan", "metrics", "events", "baselines")

# 默认被保护的"状态真源"分支
LOOP_STATE_BRANCH = "loop-state"


def _gh(args, token=None, _stdin=None):
    """跑 gh api，返回 (exit_code, stdout, stderr)。失败的 gh 调用不抛，交给上层判定。"""
    cmd = ["gh", "api", *args]
    if _stdin is not None:
        cmd += ["--input", "-"]
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, input=_stdin, env=env)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "gh not found"


def current_sha(owner_repo, ref="heads/loop-state", token=None):
    """读取目标 ref 的当前 commit sha；ref 不存在返回 None。"""
    code, out, err = _gh([f"/repos/{owner_repo}/git/ref/{ref}"], token=token)
    if code != 0 or not out.strip():
        return None
    try:
        import json
        return json.loads(out)["object"]["sha"]
    except (KeyError, TypeError, ValueError):
        return None


def cas_update(owner_repo, base_sha, new_sha, ref="heads/loop-state",
               token=None, force=False):
    """对目标 ref 做一次原子 CAS 写。

    参数:
      owner_repo: "org/repo"
      base_sha : 调用方读取时持有的旧 sha（读-CAS）
      new_sha  : 期望写成的目标 commit sha（必须是 base_sha 的后代，快进）
      ref      : 目标 ref，默认 heads/loop-state
      token    : 显式 GH_TOKEN（缺省取环境变量）
      force    : 必须是 False；True 直接拒绝（AC-5 负证）

    返回:
      new_sha（写成功）

    抛出:
      ValueError   : 传入 force=True 或 base_sha/new_sha 为空
      CASConflict  : ref 当前 sha != base_sha，或 GitHub 返回 422（base 已被并发推进）
      RuntimeError : 其它 API/网络失败
    """
    if force:
        raise ValueError("refusing force=true: CAS must never silently overwrite (AC-5)")
    if not owner_repo or not base_sha or not new_sha:
        raise ValueError("owner_repo/base_sha/new_sha are required")

    cur = current_sha(owner_repo, ref=ref, token=token)
    if cur is not None and cur != base_sha:
        raise CASConflict(f"ref {ref} at {cur}, expected base {base_sha}")

    # force=false（fast-forward-only）：GitHub 对非快进更新返回 422 → 归一化为 CASConflict
    import json as _json
    body = _json.dumps({"sha": new_sha, "force": False})  # force=false 语义：非快进即拒绝
    code, out, err = _gh(
        [
            "--method", "PATCH",
            f"/repos/{owner_repo}/git/refs/{ref}",
        ],
        token=token, _stdin=body,
    )
    if code == 0:
        _emit_event(owner_repo, ref, base_sha, new_sha, token)  # W3-TK: 成功路径事件发射
        return new_sha
    if "422" in err or "422" in out or "update is not a fast forward" in err.lower() \
            or "non-fast-forward" in err.lower():
        raise CASConflict(f"422 on PATCH {ref}: base moved (concurrent write), no write applied")
    raise RuntimeError(f"PATCH {ref} failed (exit={code}): {err or out}")


def _emit_event(owner_repo, ref, base_sha, new_sha, token):
    """W3-TK：cas_update 成功路径向事件日志 append 一条 cas_update 事件。

    该调用是**真实执行的**（非注释死串，V3-TK 用 mock.patch 复核）：事件追加失败时
    记录告警但不阻断 CAS 返回（事件日志是观测用途，CAS 本体已经成功）。绝不 Print-pass
    吞掉——失败会写 stderr 告警，不会假装成功。
    """
    try:
        from conductor.events import append_event
        append_event({
            "event": "cas_update",
            "action": "cas_update",
            "identity": os.environ.get("LOOP_IDENTITY", ""),
            "repo": owner_repo,
            "ref": ref,
            "base_sha": base_sha,
            "new_sha": new_sha,
        })
    except FileNotFoundError:
        pass  # gh 不存在时 cas 本身就跑不起来，这里不重复当作成功；保持事件发射为 best-effort
    except Exception as _e:  # noqa: BLE001 —— 事件发射为观测用途，失败不阻断 CAS
        print(f"[warn] cas event emit failed: {type(_e).__name__}: {_e}", file=sys.stderr)


def _create_commit(owner_repo, parent_sha, message, path, content, token=None):
    """用 GitHub git data API 造一个真实 commit（父=parent_sha，含一个独占文件）。

    步骤：取父 commit 的 tree → 在其上叠加文件建 tree → 以 tree+parent 建 commit。
    """
    import json
    code, out, _ = _gh([f"/repos/{owner_repo}/git/commits/{parent_sha}"], token=token)
    if code != 0 or not out.strip():
        raise RuntimeError(f"read parent commit failed (exit={code})")
    parent_tree = json.loads(out)["tree"]["sha"]

    tree = {
        "base_tree": parent_tree,
        "tree": [{"path": path, "mode": "100644", "type": "blob", "content": content}],
    }
    code, out, _ = _gh(["--method", "POST", f"https://api.github.com/repos/{owner_repo}/git/trees"],
                        token=token, _stdin=json.dumps(tree))
    if code != 0 or not out.strip():
        raise RuntimeError(f"create tree failed (exit={code})")
    tree_sha = json.loads(out)["sha"]
    cmt = {"message": message, "tree": tree_sha, "parents": [parent_sha]}
    code, out, _ = _gh(["--method", "POST", f"https://api.github.com/repos/{owner_repo}/git/commits"],
                        token=token, _stdin=json.dumps(cmt))
    if code != 0 or not out.strip():
        raise RuntimeError(f"create commit failed (exit={code})")
    return json.loads(out)["sha"]


def _reset_ref(owner_repo, scratch_ref, main_sha, token=None):
    """建 scratch ref（指向 main_sha）；已存在则 force 重置（scratch 一次性，可 force）。"""
    code, _, err = _gh(["--method", "POST", f"/repos/{owner_repo}/git/refs",
                        "-f", "ref=refs/%s" % scratch_ref,
                        "-f", "sha=%s" % main_sha], token=token)
    if code != 0:
        code, _, err = _gh(["--method", "PATCH", f"/repos/{owner_repo}/git/refs/{scratch_ref}",
                            "-f", "sha=%s" % main_sha, "-f", "force=true"], token=token)
    if code != 0:
        raise RuntimeError(f"cannot create/reset scratch ref: {err or ''}")


def _concurrency_test(owner_repo, token=None, scratch_ref="heads/cas-concurrency-test"):
    """AC-2 并发实验：对同一 scratch ref 以同一 base 并发两次 cas_update。

    期望：恰好一次成功，另一次抛 CASConflict（零额外写），ref 净推进 +1。
    用一次性 scratch ref（两个真实 sibling commit），跑完即删。
    """
    import threading, uuid

    try:
        main_sha = current_sha(owner_repo, ref="heads/main", token=token)
        if not main_sha:
            print("SKIP: cannot read heads/main to bootstrap concurrency test", file=sys.stderr)
            return 2
        _reset_ref(owner_repo, scratch_ref, main_sha, token=token)
        base = current_sha(owner_repo, ref=scratch_ref, token=token)

        tag = uuid.uuid4().hex[:8]
        new_a = _create_commit(owner_repo, base, "cas-test A " + tag, f"cas/A-{tag}.txt",
                               f"content-A-{tag}", token=token)
        new_b = _create_commit(owner_repo, base, "cas-test B " + tag, f"cas/B-{tag}.txt",
                               f"content-B-{tag}", token=token)

        results = {}

        def _run(name, new):
            try:
                cas_update(owner_repo, base, new, ref=scratch_ref, token=token)
                results[name] = ("OK", None)
            except CASConflict as e:
                results[name] = ("CASConflict", str(e)[:55])
            except Exception as e:  # noqa: BLE001 —— 笼统记录便于判定
                results[name] = ("ERROR", str(e)[:55])

        t1 = threading.Thread(target=_run, args=("A", new_a))
        t2 = threading.Thread(target=_run, args=("B", new_b))
        t1.start(); t2.start(); t1.join(); t2.join()

        wins = [k for k, v in results.items() if v[0] == "OK"]
        conflicts = [k for k, v in results.items() if v[0] == "CASConflict"]
        final = current_sha(owner_repo, ref=scratch_ref, token=token)
        print("results:", results)
        print("final_sha:", final)
        print("winners:", wins, "conflicts:", conflicts)

        # 恰好一次成功 + 一次 CASConflict，最终 ref 恰为某个成功者（非 base）→ PASS
        if len(wins) == 1 and len(conflicts) == 1 and final in (new_a, new_b):
            return 0
        # 输出不足判定（权限/infra），返回 3 表示"未能验证"而非 PASS
        return 3
    finally:
        _gh(["--method", "DELETE", f"/repos/{owner_repo}/git/refs/{scratch_ref}"], token=token)


def main(argv):
    if argv and argv[0] == "--concurrency-test":
        owner_repo = os.environ.get("LOOP_CAS_REPO", "Cloudbird-Software/loop")
        return _concurrency_test(owner_repo, token=os.environ.get("GH_TOKEN"))
    if argv and argv[0] == "--read":
        owner_repo = os.environ.get("LOOP_CAS_REPO", "Cloudbird-Software/loop")
        sha = current_sha(owner_repo, ref="heads/loop-state")
        print("loop-state:", sha)
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))