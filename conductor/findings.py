#!/usr/bin/env python3
"""conductor/findings.py — Finding 生命周期管理（R14-1）。

统一负责：
  - 按 fingerprint 查重，同一 lens/位置不重复开单
  - 首次发现 → 创建真实 GitHub issue，返回 issue number
  - 重复发现 → 在已有 issue 下追加 comment，bump occurrences
  - 提供关闭 stale finding 的入口

所有 write 操作均要求环境变量 GH_TOKEN 已配置。
"""
import json
import os
import re
import subprocess
import sys
from typing import Optional


def _repo() -> str:
    E = os.environ
    org = E.get("LOOP_ORG") or E.get("GITHUB_REPOSITORY_OWNER", "")
    repo = E.get("LOOP_REPO") or (
        E.get("GITHUB_REPOSITORY", "loop").split("/")[-1]
        if "/" in E.get("GITHUB_REPOSITORY", "")
        else "loop"
    )
    return f"{org}/{repo}" if org else E.get("GITHUB_REPOSITORY", "Cloudbird-Software/loop")


def _gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def _extract_issue_number(url_or_text: str) -> int:
    """从 gh issue create 返回的 URL 或 '#123' 字符串中提取 issue number。"""
    url_or_text = url_or_text.strip()
    m = re.search(r"/issues/(\d+)", url_or_text)
    if m:
        return int(m.group(1))
    m = re.search(r"#(\d+)", url_or_text)
    if m:
        return int(m.group(1))
    # 最后一搏：纯数字
    m = re.search(r"(\d+)$", url_or_text)
    if m:
        return int(m.group(1))
    raise ValueError(f"无法从 gh 输出解析 issue number: {url_or_text!r}")


def search_open_finding(repo: str, fingerprint: str) -> Optional[int]:
    """按 fingerprint 搜索 open 的 finding issue；命中则返回 issue number，否则 None。"""
    p = _gh(
        "issue", "list", "-R", repo,
        "--state", "open", "--label", "finding",
        "--limit", "200", "--json", "number,body"
    )
    if p.returncode != 0:
        return None
    try:
        issues = json.loads(p.stdout or "[]")
    except json.JSONDecodeError:
        return None
    marker = f"fingerprint: `{fingerprint}`"
    for it in issues:
        body = it.get("body") or ""
        if marker in body or f'"fingerprint": "{fingerprint}"' in body:
            return int(it["number"])
    return None


def _body_for_finding(fingerprint: str, lens: str, shard: str,
                      severity: str, occurrences: int, raw: dict) -> str:
    """生成 Finding issue 正文。包含 machine-readable fingerprint 标记用于查重。"""
    raw_json = json.dumps(raw, indent=2, ensure_ascii=False)
    return f"""## Finding

- **fingerprint**: `{fingerprint}`
- **lens**: `{lens}`
- **shard**: `{shard}`
- **severity**: `{severity}`
- **occurrences**: `{occurrences}`

### raw

```json
{raw_json}
```
"""


def open_finding(fingerprint: str, lens: str, shard: str,
                 severity: str, occurrences: int, raw: dict,
                 repo: Optional[str] = None) -> int:
    """为首次发现创建真实 GitHub issue；若已存在同 fingerprint 的 open issue 则追加 comment。

    返回真实 issue number。
    """
    repo = repo or _repo()
    existing = search_open_finding(repo, fingerprint)
    if existing is not None:
        body = (
            f"🔁 重复发现（occurrences={occurrences}）\n\n"
            f"- lens: `{lens}`\n"
            f"- shard: `{shard}`\n"
            f"- severity: `{severity}`"
        )
        _gh("issue", "comment", str(existing), "-R", repo, "--body", body)
        return existing

    title = f"Finding [{lens}/{shard}]: {raw.get('message', fingerprint[:48])}"
    body = _body_for_finding(fingerprint, lens, shard, severity, occurrences, raw)
    p = _gh("issue", "create", "-R", repo, "--title", title,
            "--body", body, "--label", "finding")
    if p.returncode != 0:
        raise RuntimeError(f"gh issue create failed: {p.stderr}")
    return _extract_issue_number(p.stdout)


def comment_finding(issue_number: int, body: str, repo: Optional[str] = None) -> None:
    repo = repo or _repo()
    p = _gh("issue", "comment", str(issue_number), "-R", repo, "--body", body)
    if p.returncode != 0:
        raise RuntimeError(f"gh issue comment failed: {p.stderr}")


def close_finding(issue_number: int, reason: str, repo: Optional[str] = None) -> None:
    """关闭 stale finding 并追加说明。"""
    repo = repo or _repo()
    _gh("issue", "comment", str(issue_number), "-R", repo,
        "--body", f"✅ 自动关闭：{reason}")
    _gh("issue", "close", str(issue_number), "-R", repo,
        "--comment", "closed by conductor/findings.py stale cleanup")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="创建或更新 finding issue")
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--lens", required=True)
    ap.add_argument("--shard", default="S0")
    ap.add_argument("--severity", default="low")
    ap.add_argument("--occurrences", type=int, default=1)
    ap.add_argument("--raw", default="{}", help="JSON string")
    ap.add_argument("--repo")
    args = ap.parse_args()
    num = open_finding(
        args.fingerprint, args.lens, args.shard,
        args.severity, args.occurrences,
        json.loads(args.raw),
        repo=args.repo,
    )
    print(num)
