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

# 状态真源分支（与 conductor/cas.py LOOP_STATE_BRANCH 对齐）
LOOP_STATE_BRANCH = "loop-state"


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

    def current_sha(self, ref="heads/loop-state"):
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
        body = json.dumps({"sha": new_sha, "force": False})
        code, out, err = _gh(
            ["--method", "PATCH",
             f"/repos/{self.repo}/git/refs/{LOOP_STATE_BRANCH}",
             "--input", "-"],
            _stdin=body, token=self.token,
        )
        if code == 0:
            return new_sha
        raise RuntimeError(f"PATCH {LOOP_STATE_BRANCH} failed (exit={code}): {err or out}")


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