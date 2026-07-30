#!/usr/bin/env python3
"""conductor/scan_workflows.py — workflow 静态扫描器（R10-1）。

从 pr-ci.yml 的 no-fake-green / actions-pinned 两个 job 中抽出的扫描逻辑本体。
pr-ci.yml 暂保留内联副本（R11-1 收口为调用本模块），但负向测试必须调用这里，
不得复制粘贴一份平行实现。

两个扫描器都返回 violations 列表（空 = 合规，非空 = 违规）。
"""
import glob
import os
import re

ALLOW_MARK = "fake-green-ok:"

# 假绿模式：吞掉失败的写法。每条 (正则, 描述)。
FAKE_GREEN_PATTERNS = [
    (r"\|\|\s*true\b", "`|| true` 吞掉失败"),
    (r"^\s*set\s+\+e\b", "`set +e` 关闭错误传播"),
    (r"continue-on-error:\s*true", "continue-on-error"),
]

# uses: 引用必须钉到 40 位 SHA（CHARTER N4）。
USES_RE = re.compile(r"^(?:-?\s*uses:)\s+(.+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _workflow_files(workflows_dir=".github/workflows"):
    """返回 workflow 文件路径列表，接受目录或单文件。"""
    if os.path.isdir(workflows_dir):
        return sorted(glob.glob(os.path.join(workflows_dir, "*.yml")))
    if os.path.isfile(workflows_dir):
        return [workflows_dir]
    return []


def scan_no_fake_green(workflows_dir=".github/workflows"):
    """扫描 workflow 中的吞错模式（|| true / set +e / continue-on-error）。

    合规例外：在该行或上一行写 `fake-green-ok: <理由>`。注释行不算实际行为。
    返回 violations 列表，每条 "file:line: desc → stripped_line"。
    """
    violations = []
    for f in _workflow_files(workflows_dir):
        lines = open(f, encoding="utf-8").read().splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            ctx = line + (lines[i - 1] if i else "")
            if ALLOW_MARK in ctx:
                continue
            for pat, desc in FAKE_GREEN_PATTERNS:
                if re.search(pat, line):
                    violations.append(f"{f}:{i + 1}: {desc} → {stripped}")
    return violations


def scan_actions_pinned(workflows_dir=".github/workflows"):
    """校验所有 uses 引用钉到 40 位 commit SHA。

    本地引用（./）与 docker:// 跳过。返回 violations 列表。
    """
    violations = []
    for f in _workflow_files(workflows_dir):
        for i, line in enumerate(open(f, encoding="utf-8").read().splitlines()):
            s = line.strip()
            m = USES_RE.match(s)
            if not m:
                continue
            ref = m.group(1).strip().strip("'\"").split()[0]
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            if "@" not in ref:
                violations.append(f"{f}:{i + 1}: 无 ref → {ref}")
                continue
            sha = ref.rsplit("@", 1)[1]
            if not SHA_RE.fullmatch(sha):
                violations.append(f"{f}:{i + 1}: 未钉 SHA → {ref}")
    return violations
