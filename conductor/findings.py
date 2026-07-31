#!/usr/bin/env python3
"""conductor/findings.py — Finding 的统一管理（R14-1）。

替代此前散落在 audit.yml 与 tick.py 中的 finding 处理逻辑：把 lens 产出的
证据真正落进 GitHub issue 系统，而非用 `abs(hash(fp))` 造一个指向不存在的
临时编号。

提供四个原子操作 + 一个稳定指纹：
- create_finding(...)    创建 GitHub issue，返回真实 issue 编号（int）
- find_open_finding(...) 按指纹查重，返回已存在的开 issue 编号或 None
- update_finding(...)    向已有 finding 追加评论（更新 occurrences/last_seen）
- close_finding(...)     关闭 finding 并附理由评论
- fingerprint(...)       SHA-256 稳定指纹，输出格式与 conductor.tick.fingerprint
                         完全一致（sha256("lens|path|symbol|rule_id")[:16]），
                         因此两者可互换使用，不破坏现有 state.json 中的指纹键。

所有 gh 调用走 subprocess.run(["gh", ...])，失败抛 RuntimeError（不静默）。
FINDINGS_DRY_RUN=1 时不实际调 gh，只打印将做什么，create_finding 返回假号 999999。
"""
import hashlib
import json
import os
import subprocess

E = os.environ

LENS_FINDING_LABEL = "lens-finding"
DRY_RUN_FAKE_NUMBER = 999999


def _dry_run():
    """FINDINGS_DRY_RUN=1 → 只打印不触网。"""
    return E.get("FINDINGS_DRY_RUN") == "1"


def _resolve_repo(repo):
    """解析目标仓库：显式 repo 优先；否则 LOOP_ORG + LOOP_REPO（默认 loop 控制面）。"""
    if repo:
        return repo
    org = E.get("LOOP_ORG") or E.get("GITHUB_REPOSITORY_OWNER") or ""
    name = E.get("LOOP_REPO") or "loop"
    return f"{org}/{name}" if org else name


def fingerprint(lens, path, symbol, rule_id):
    """稳定指纹：sha256("lens|path|symbol|rule_id") 前 16 位 hex。

    与 conductor.tick.fingerprint 实现完全一致——同一根因无论在哪条路径上检出
    都得到同一指纹，作为查重键贯穿 state.json / issue 搜索 / closed_findings。
    不用 abs(hash(fp))（那是进程内不稳定哈希，且绝非 issue 号）。
    """
    s = f"{lens}|{path}|{symbol}|{rule_id}".encode()
    return hashlib.sha256(s).hexdigest()[:16]


def _build_body(lens, path, symbol, rule_id, severity, raw, fp):
    """组装 finding issue body：含 severity/lens/path/symbol/rule_id/证据/指纹。

    指纹以明文写入 body，供 find_open_finding 的 `--search <fp>` 命中。
    """
    lines = [
        "## Lens Finding",
        "",
        f"- **Lens**: `{lens}`",
        f"- **Path**: `{path}`",
        f"- **Symbol**: `{symbol}`",
        f"- **Rule ID**: `{rule_id}`",
        f"- **Severity**: `{severity}`",
        f"- **Fingerprint**: `{fp}` (SHA-256 前 16 位，稳定查重键)",
        "",
        "### Evidence (raw)",
        "```json",
        json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ]
    return "\n".join(lines)


def _ensure_label(repo, name=LENS_FINDING_LABEL):
    """确保 label 存在；已存在则跳过，其它失败抛 RuntimeError。"""
    if _dry_run():
        print(f"[dry-run] would ensure label {name} in {repo}")
        return
    p = subprocess.run(
        ["gh", "label", "create", name, "-R", repo, "--color", "D93F0B"],
        capture_output=True, text=True,
    )
    if p.returncode == 0:
        return
    # gh 对重复 label 报 already_exists / already exists —— 容忍
    combined = ((p.stdout or "") + (p.stderr or "")).lower()
    if "exist" in combined:
        return
    raise RuntimeError(
        f"gh label create 失败 ({p.returncode}): {' '.join(['gh', 'label', 'create', name, '-R', repo])}\n"
        f"stderr: {p.stderr}")


def create_finding(lens, path, symbol, rule_id, severity, raw, repo=None):
    """创建 GitHub finding issue，返回 issue 编号（int）。

    标题：[Finding] <lens> <path>:<symbol> (<rule_id>)
    Body：severity / lens / path / symbol / rule_id / raw 证据 / fingerprint
    Label：lens-finding（不存在则先建）
    """
    fp = fingerprint(lens, path, symbol, rule_id)
    repo = _resolve_repo(repo)
    title = f"[Finding] {lens} {path}:{symbol} ({rule_id})"
    body = _build_body(lens, path, symbol, rule_id, severity, raw, fp)

    if _dry_run():
        print(f"[dry-run] would create finding: {title} (fp={fp}) in {repo}")
        return DRY_RUN_FAKE_NUMBER

    _ensure_label(repo, LENS_FINDING_LABEL)
    p = subprocess.run(
        ["gh", "issue", "create", "-R", repo,
         "--title", title, "--body", body, "--label", LENS_FINDING_LABEL],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"gh issue create 失败 ({p.returncode}): {title}\nstderr: {p.stderr}")
    # gh issue create 输出 issue URL，取末段数字作为编号
    out = (p.stdout or "").strip()
    last_line = out.splitlines()[-1].strip() if out else ""
    try:
        num = int(last_line.rstrip("/").split("/")[-1])
    except (ValueError, IndexError):
        raise RuntimeError(
            f"无法从 gh issue create 输出解析 issue 编号: {out!r}")
    print(f"→ created finding #{num}: {title} (fp={fp})")
    return num


def find_open_finding(fingerprint, repo=None):
    """按指纹查重：返回同指纹且仍 open 的 finding issue 编号，或 None。

    用 `gh issue list --label lens-finding --state open --search <fp>`，
    --search 会匹配 title/body/comments，故能命中 body 中写入的指纹明文。
    """
    repo = _resolve_repo(repo)
    if _dry_run():
        print(f"[dry-run] would search open finding fp={fingerprint} in {repo}")
        return None
    p = subprocess.run(
        ["gh", "issue", "list", "-R", repo,
         "--label", LENS_FINDING_LABEL, "--state", "open",
         "--search", str(fingerprint),
         "--json", "number", "--limit", "10"],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"gh issue list 失败 ({p.returncode})\nstderr: {p.stderr}")
    try:
        items = json.loads(p.stdout or "[]")
    except json.JSONDecodeError:
        return None
    for it in items:
        n = it.get("number")
        if n is not None:
            return int(n)
    return None


def update_finding(issue_number, note, repo=None):
    """向已有 finding issue 追加评论（更新 occurrences / last_seen 等）。"""
    repo = _resolve_repo(repo)
    if _dry_run():
        print(f"[dry-run] would comment on finding #{issue_number} in {repo}: {note}")
        return
    p = subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "-R", repo, "--body", note],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"gh issue comment 失败 ({p.returncode}) on #{issue_number}\nstderr: {p.stderr}")


def close_finding(issue_number, reason, repo=None):
    """关闭 finding issue 并附理由评论（先评论后关闭）。"""
    repo = _resolve_repo(repo)
    if _dry_run():
        print(f"[dry-run] would close finding #{issue_number} in {repo}: {reason}")
        return
    # 先附理由评论，再关闭——两步都失败即抛
    pc = subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "-R", repo, "--body", reason],
        capture_output=True, text=True,
    )
    if pc.returncode != 0:
        raise RuntimeError(
            f"gh issue comment 失败 ({pc.returncode}) on #{issue_number}\nstderr: {pc.stderr}")
    pcl = subprocess.run(
        ["gh", "issue", "close", str(issue_number), "-R", repo],
        capture_output=True, text=True,
    )
    if pcl.returncode != 0:
        raise RuntimeError(
            f"gh issue close 失败 ({pcl.returncode}) on #{issue_number}\nstderr: {pcl.stderr}")
