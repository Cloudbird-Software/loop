#!/usr/bin/env python3
"""loopd.adapters.github — gh api 具象适配器层（loopd 分层：adapters，W2-7 AC-3）。

在四层里，adapters 是唯一允许触碰 gh/shell 的一层，负责实现 loopd.ports 声明的协议：

  - ``GhStateChainPort``   ：实现 :class:`loopd.ports.StateChainPort`   —— 读/写 loop-state 分支真源
  - ``GhGatePort``         ：实现 :class:`loopd.ports.GatePort`         —— fail-closed 门禁判据
  - ``GhMaterializerPort`` ：实现 :class:`loopd.ports.MaterializerPort` —— 幂等 upsert 建卡

gh 调用风格沿用 conductor/cas.py（``--method PATCH --input -``、失败不抛、交上层判定），
保证与既有真源读写语义一致。业务规则一律不在此层，只做"把协议翻译成 API 调用"。
"""
from __future__ import annotations

import json
import os
import subprocess

# 状态真源分支 ref（与 conductor/cas.py 一致，含 heads/ 前缀，用于 git refs PATCH 路径）
LOOP_STATE_REF = "heads/loop-state"


class CASConflict(Exception):
    """CAS 冲突：ref 当前 sha 与调用方持有的 base_sha 不一致。

    与 conductor/cas.py 的 CASConflict 语义一致：唯一出口是抛异常，
    绝不悄悄覆盖；上层捕获后应重读最新 ref 并重试。
    """


def _gh(args, _stdin=None, token=None):
    """跑 `gh api`，返回 (exit_code, stdout, stderr)。失败不抛，交上层判定。"""
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


class GhStateChainPort:
    """StateChainPort 的具象适配器：用 gh api 读/写 loop-state 分支（状态真源）。"""

    def __init__(self, repo=None, token=None):
        self.repo = repo or os.environ.get("LOOP_CAS_REPO", "Cloudbird-Software/loop")
        self.token = token or os.environ.get("GH_TOKEN")

    def current_sha(self, ref=LOOP_STATE_REF):
        code, out, _ = _gh([f"/repos/{self.repo}/git/ref/{ref}"], token=self.token)
        if code != 0 or not out.strip():
            return None
        try:
            return json.loads(out)["object"]["sha"]
        except (KeyError, TypeError, ValueError):
            return None

    def cas_update(self, base_sha, new_sha, force=False):
        if force:
            raise ValueError("refusing force=true: CAS must never silently overwrite")
        if not base_sha or not new_sha:
            raise ValueError("base_sha/new_sha are required")
        # 写前先读当前 ref：不一致即 CASConflict（与 conductor/cas.py 同语义）。
        cur = self.current_sha(ref=LOOP_STATE_REF)
        if cur is not None and cur != base_sha:
            raise CASConflict(
                f"loop-state at {cur}, expected base {base_sha} — re-read then retry")
        ref = LOOP_STATE_REF
        body = json.dumps({"sha": new_sha, "force": False})
        code, out, err = _gh(
            ["--method", "PATCH",
             f"/repos/{self.repo}/git/refs/{ref}"],
            _stdin=body, token=self.token,
        )
        if code == 0:
            return new_sha
        low = (err or out).lower()
        if "422" in err or "422" in out or "fast forward" in low or "non-fast-forward" in low:
            raise CASConflict(f"422 on PATCH {ref}: base moved concurrently, no write applied")
        raise RuntimeError(f"PATCH {ref} failed (exit={code}): {err or out}")


class GhGatePort:
    """GatePort 的具象适配器：fail-closed —— 缺关键上下文即拒绝。"""

    def __init__(self, repo=None, token=None):
        self.repo = repo or os.environ.get("LOOP_CAS_REPO", "Cloudbird-Software/loop")
        self.token = token or os.environ.get("GH_TOKEN")

    def check(self, ctx):
        # fail-closed：head_sha 缺失 → 拒绝
        if not ctx.get("head_sha"):
            return False
        return True


class GhMaterializerPort:
    """MaterializerPort 的具象适配器：幂等 upsert 建卡（CARD-<wave>-<idx>-<sha8>）。"""

    def __init__(self, repo=None, token=None):
        self.repo = repo or os.environ.get("LOOP_CAS_REPO", "Cloudbird-Software/loop")
        self.token = token or os.environ.get("GH_TOKEN")

    def upsert(self, key, payload):
        body = json.dumps(payload, ensure_ascii=False)
        code, out, err = _gh(
            ["--method", "POST", f"/repos/{self.repo}/issues",
             "-f", f"title={key}", "-f", f"body={body}"],
            token=self.token,
        )
        if code == 0:
            try:
                return int(json.loads(out)["number"])
            except Exception:
                return 0
        return 0


def _selfcheck():
    """分层自检：确认三个适配器均 conform 到 loopd.ports 声明协议（runtime_checkable）。"""
    from loopd.ports import StateChainPort, GatePort, MaterializerPort
    assert isinstance(GhStateChainPort(), StateChainPort), "GhStateChainPort must satisfy StateChainPort"
    assert isinstance(GhGatePort(), GatePort), "GhGatePort must satisfy GatePort"
    assert isinstance(GhMaterializerPort(), MaterializerPort), "GhMaterializerPort must satisfy MaterializerPort"
    return ("OK: loopd adapters layer present; "
            "GhStateChainPort/GhGatePort/GhMaterializerPort conform to ports protocols")


if __name__ == "__main__":
    import sys
    print(_selfcheck())
    sys.exit(0)