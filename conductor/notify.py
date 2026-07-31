#!/usr/bin/env python3
"""conductor/notify.py — 通知通道（R14-2）。

落地最小可行通知：
  - 波次通过/失败 → 在 WAVE 父 issue 下评论
  - 需要人类介入 → 创建/评论 human-verify issue
  - Incident 升级 → 创建/评论 incident issue

未来可替换为 Slack/飞书/Webhook；当前以 GitHub issue 为唯一真源，不引入外部依赖。
"""
import json
import os
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


def comment_issue(repo: str, issue_number: int, body: str) -> None:
    p = _gh("issue", "comment", str(issue_number), "-R", repo, "--body", body)
    if p.returncode != 0:
        raise RuntimeError(f"notify comment failed: {p.stderr}")


def create_issue(repo: str, title: str, body: str, labels: str) -> int:
    p = _gh("issue", "create", "-R", repo, "--title", title, "--body", body, "--label", labels)
    if p.returncode != 0:
        raise RuntimeError(f"notify create issue failed: {p.stderr}")
    url = p.stdout.strip()
    try:
        return int(url.split("/issues/")[-1].split("#")[0])
    except Exception:
        raise RuntimeError(f"无法解析 issue number from: {url}")


def wave_result(wave_id: str, passed: bool, detail_json: dict, repo: Optional[str] = None):
    """波次验收结果通知：评论到 WAVE 父 issue。"""
    repo = repo or _repo()
    # 找 wave 父 issue
    p = _gh("issue", "list", "-R", repo, "--state", "open", "--label", "wave",
            "--search", wave_id, "--limit", "5", "--json", "number,title")
    if p.returncode != 0:
        raise RuntimeError(p.stderr)
    issues = json.loads(p.stdout or "[]")
    number = None
    for it in issues:
        if wave_id in it.get("title", ""):
            number = it["number"]
            break
    if number is None:
        # 找不到 open 父 issue 则创建一个
        number = create_issue(repo, f"[Notify] {wave_id} 验收结果", "", "notify")
    status = "✅ 通过" if passed else "❌ 未通过"
    body = f"## {wave_id} 自动验收结果：{status}\n\n```json\n{json.dumps(detail_json, indent=2, ensure_ascii=False)}\n```"
    comment_issue(repo, number, body)
    return number


def human_attention(wave_id: str, checklist: list, repo: Optional[str] = None):
    """需要人类介入：创建/评论 human-verify issue。"""
    repo = repo or _repo()
    title = f"[human-verify] {wave_id} 待人工确认项"
    items = "\n".join(f"- [ ] {c.get('number', '?')}. {c.get('text', '')}" for c in checklist)
    body = f"{wave_id} 的自动验收判定 human-verify 项超过阈值或存在待确认项，需要人类介入：\n\n{items}\n\n确认后请在对应 evidence/ 目录补充 `.md` 证据并重新运行验收。"
    # 搜索是否已有同标题 open issue
    p = _gh("issue", "list", "-R", repo, "--state", "open", "--label", "human-verify",
            "--search", wave_id, "--limit", "5", "--json", "number,title")
    existing = None
    for it in json.loads(p.stdout or "[]"):
        if wave_id in it.get("title", ""):
            existing = it["number"]
            break
    if existing:
        comment_issue(repo, existing, body)
        return existing
    return create_issue(repo, title, body, "human-verify")


def incident(level: str, summary: str, context: dict, repo: Optional[str] = None):
    """Incident 升级通知：创建 incident issue。"""
    repo = repo or _repo()
    title = f"[incident/{level}] {summary[:80]}"
    body = f"**级别**: {level}\n**时间**: {context.get('ts', 'now')}\n\n```json\n{json.dumps(context, indent=2, ensure_ascii=False)}\n```"
    return create_issue(repo, title, body, f"incident,{level}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="通知通道 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("wave-result", help="波次验收结果")
    p1.add_argument("--wave", required=True)
    p1.add_argument("--passed", type=lambda x: x.lower() in ("1", "true", "yes"), required=True)
    p1.add_argument("--detail", default="{}")
    p1.add_argument("--repo")

    p2 = sub.add_parser("human-attention", help="需要人类介入")
    p2.add_argument("--wave", required=True)
    p2.add_argument("--checklist", default="[]")
    p2.add_argument("--repo")

    p3 = sub.add_parser("incident", help="Incident 升级")
    p3.add_argument("--level", required=True)
    p3.add_argument("--summary", required=True)
    p3.add_argument("--context", default="{}")
    p3.add_argument("--repo")

    args = ap.parse_args()
    if args.cmd == "wave-result":
        wave_result(args.wave, args.passed, json.loads(args.detail), repo=args.repo)
    elif args.cmd == "human-attention":
        human_attention(args.wave, json.loads(args.checklist), repo=args.repo)
    elif args.cmd == "incident":
        incident(args.level, args.summary, json.loads(args.context), repo=args.repo)
