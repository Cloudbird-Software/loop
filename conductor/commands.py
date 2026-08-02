#!/usr/bin/env python3
"""conductor/commands.py — 波次 PR 微指令解析与执行（W4-4）。

解析 !drop/!add/!defer/!answer 微指令：
- !drop O2       → 从波次文件中移除目标 O2 及其关联卡片
- !add <desc>    → 向波次文件追加一个新目标
- !defer O2      → 将目标 O2 延期到下一个波次（从当前移除，记入 not_doing）
- !answer <text> → 回答 planner 的唯一问题，触发修订

约束：
- planner 修订上限 2 轮（超过则拒绝，提示人类直接 Approve 或手动编辑）
- force-push 同一分支（不开新分支）
- 只有 wave PR 的评论才响应（非 wave PR 忽略）
- 只有白名单作者（COMMAND_AUTHORS 或 team.yml）可触发微指令

用法（由 issue_comment workflow 调用）：
  python conductor/commands.py --pr <number> --comment <body> --author <login>

或通过环境变量：
  PR_NUMBER, COMMENT_BODY, COMMENT_AUTHOR
"""
import json, os, subprocess, sys, re, pathlib, argparse, time

# schema 字段名单一事实源（W2-5 / I-001）：造卡模板里的键名不裸硬编码。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from conductor.schema_types import CARD_FIELD_LEASE_UNTIL

E = os.environ
REPO = f'{E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER",""))}/{E.get("LOOP_REPO","product-x")}'
MAX_REVISIONS = 2


def gh(*a):
    return subprocess.run(["gh", *a], capture_output=True, text=True)


def sh(*a, **kw):
    return subprocess.run(list(a), capture_output=True, text=True, **kw)


# ============================================================
# Author whitelist (one-way valve: only whitelisted users trigger commands)
# ============================================================

def _load_allowed_authors():
    """加载评论作者白名单。

    优先从环境变量 COMMAND_AUTHORS 读取（逗号分隔）；否则尝试 team.yml
    （支持 command_authors/members/authors/users 列表，元素可为字符串或
    含 login 字段的 dict）。返回空集合表示未配置白名单（向后兼容放行）。
    """
    raw = E.get("COMMAND_AUTHORS", "").strip()
    if raw:
        return {a.strip().lstrip("@") for a in raw.split(",") if a.strip()}
    # 回退：team.yml
    for path in ("team.yml", "TEAM.yml", ".loop/team.yml"):
        p = pathlib.Path(path)
        if p.exists():
            try:
                import yaml
                data = yaml.safe_load(p.read_text()) or {}
                if isinstance(data, dict):
                    for key in ("command_authors", "members", "authors", "users"):
                        vals = data.get(key)
                        if isinstance(vals, list):
                            names = set()
                            for v in vals:
                                if isinstance(v, str):
                                    names.add(v.strip().lstrip("@"))
                                elif isinstance(v, dict) and v.get("login"):
                                    names.add(str(v["login"]).strip().lstrip("@"))
                            if names:
                                return names
            except Exception:
                pass
    return set()


# ============================================================
# PR / Wave file helpers
# ============================================================

def get_pr_info(pr_number):
    """Get PR info: branch, title, body, labels, state."""
    p = gh("pr","view",str(pr_number),"-R",REPO,
           "--json","headRefName,title,body,labels,state")
    if p.returncode != 0:
        return None
    return json.loads(p.stdout)


def find_wave_file(pr_number):
    """Find the wave file modified by this PR."""
    p = gh("pr","diff",str(pr_number),"-R",REPO,"--name-only")
    if p.returncode != 0:
        return None
    for line in p.stdout.strip().splitlines():
        if line.startswith("waves/") and line.endswith(".md"):
            return line
    return None


def get_pr_comments(pr_number):
    """Get all comments on the PR."""
    p = gh("api",f"/repos/{REPO}/issues/{pr_number}/comments","--paginate")
    if p.returncode != 0:
        return []
    try:
        return json.loads(p.stdout or "[]")
    except Exception:
        return []


def count_revisions(pr_number):
    """Count how many revision rounds have been triggered by !commands."""
    comments = get_pr_comments(pr_number)
    count = 0
    for c in comments:
        body = c.get("body","")
        if body.startswith("[revision]") or body.startswith("[revision-round]"):
            count += 1
    return count


def comment_on_pr(pr_number, body):
    """Post a comment on the PR."""
    gh("issue","comment",str(pr_number),"-R",REPO,"--body",body)


# ============================================================
# Wave file manipulation
# ============================================================

def read_wave_file(filepath):
    """Read wave file content."""
    p = pathlib.Path(filepath)
    if p.exists():
        return p.read_text()
    return None


def write_wave_file(filepath, content):
    """Write wave file content."""
    pathlib.Path(filepath).write_text(content)


def extract_objectives(text):
    """Extract objectives (O1, O2, ...) and their sections from wave markdown."""
    objectives = {}
    # Match ## O1, ### O1, etc. or lines starting with O1:
    pattern = r'^(#{1,4}\s+)?(O\d+)\s*[:：]?\s*(.*)$'
    lines = text.splitlines()
    current_obj = None
    current_lines = []
    for i, line in enumerate(lines):
        m = re.match(pattern, line)
        if m:
            if current_obj:
                objectives[current_obj] = current_lines
            current_obj = m.group(2)
            current_lines = [(i, line)]
        elif current_obj:
            current_lines.append((i, line))
    if current_obj:
        objectives[current_obj] = current_lines
    return objectives


def extract_cards_from_text(text):
    """Extract all ```json loop card blocks with their positions."""
    cards = []
    for m in re.finditer(r'```json loop\n(.*?)```', text, re.DOTALL):
        try:
            card = json.loads(m.group(1).strip())
            cards.append({
                "card": card,
                "start": m.start(),
                "end": m.end(),
                "raw": m.group(0)
            })
        except json.JSONDecodeError:
            pass
    return cards


def drop_objective(text, obj_id):
    """Remove an objective and its associated cards from wave text."""
    cards = extract_cards_from_text(text)
    # Remove cards belonging to this objective
    new_text = text
    for c in reversed(cards):  # reverse to preserve offsets
        if c["card"].get("objective") == obj_id:
            new_text = new_text[:c["start"]] + new_text[c["end"]:]
    # Remove objective header and its section
    lines = new_text.splitlines()
    new_lines = []
    skip = False
    for line in lines:
        if re.match(rf'^#{{1,4}}\s+{obj_id}\s*[:：]?', line) or re.match(rf'^{obj_id}\s*[:：]', line):
            skip = True
            continue
        if skip:
            # Stop skipping when they hit another objective or a new major section
            if re.match(r'^#{1,2}\s+(O\d+|##\s)', line) or re.match(r'^O\d+\s*[:：]', line):
                skip = False
                new_lines.append(line)
            # else: skip this line (part of the dropped objective)
        else:
            new_lines.append(line)
    return "\n".join(new_lines)


def defer_objective(text, obj_id):
    """Mark an objective as deferred (move to not_doing section)."""
    # Add to not_doing section
    not_doing_pattern = r'(##\s*not_doing.*?\n)'
    defer_note = f"- {obj_id}: deferred to next wave (per human instruction)\n"

    m = re.search(not_doing_pattern, text, re.DOTALL | re.IGNORECASE)
    if m:
        insert_pos = m.end()
        text = text[:insert_pos] + defer_note + text[insert_pos:]
    else:
        # Add not_doing section at end
        text += f"\n## not_doing\n{defer_note}\n"

    # Remove cards for this objective
    cards = extract_cards_from_text(text)
    for c in reversed(cards):
        if c["card"].get("objective") == obj_id:
            text = text[:c["start"]] + text[c["end"]:]

    # Mark objective header as deferred
    text = re.sub(
        rf'(^#{{1,4}}\s+{obj_id}\s*[:：]?.*$)',
        rf'\1 — [DEFERRED to next wave]',
        text,
        flags=re.MULTILINE
    )
    return text


def add_objective(text, description, next_obj_num=None):
    """Add a new objective to the wave."""
    # Find max objective number
    objs = re.findall(r'O(\d+)', text)
    max_num = max(int(n) for n in objs) if objs else 0
    new_num = next_obj_num or (max_num + 1)
    new_obj = f"O{new_num}"

    # Add objective section before the card blocks
    # Find a good insertion point (before first ```json loop or at end)
    insert_pos = text.find("```json loop")
    if insert_pos == -1:
        insert_pos = len(text)

    section = f"""
## {new_obj}: {description}

_Objective added per human instruction._

```json loop
{{
  "schema": 1, "id": "C-ADHOC-{new_obj}", "wave": "", "objective": "{new_obj}",
  "state": "ready", "tier": "standard", "role": "impl",
  "paths": ["src/**"],
  "forbid_paths": [".github/**","settings/**","tests/acceptance/**","contracts/**",".specify/**"],
  "claim_id": null, "{CARD_FIELD_LEASE_UNTIL}": null, "heartbeat_at": null,
  "attempt": 0, "session_ordinal": null, "model": null,
  "origin": {{"kind":"human","ref":"pr-comment"}},
  "budget": {{"max_diff_lines": 600, "max_minutes": 120}},
  "acceptance": ["AC1: {description}"],
  "verify": {{"required": true, "blind": true, "verdict_sha": null}},
  "charter": ["G0"], "spec_ref": ""
}}
```
"""
    return text[:insert_pos] + section + text[insert_pos:], new_obj


# ============================================================
# Git operations (force-push same branch)
# ============================================================

def commit_and_force_push(filepath, branch, message):
    """Commit change and force-push to the same branch."""
    sh("git","add",filepath)
    sh("git","-c","user.name=loop-planner-bot",
       "-c","user.email=planner-bot@users.noreply.github.com",
       "commit","-m",message)
    result = sh("git","push","origin",branch,"--force-with-lease")
    return result.returncode == 0


# ============================================================
# Command parser
# ============================================================

COMMAND_PATTERN = re.compile(r'^!(drop|add|defer|answer)\s+(.+)', re.MULTILINE)


def parse_commands(comment_body):
    """Parse !commands from comment body. Returns list of (cmd, arg)."""
    commands = []
    for m in COMMAND_PATTERN.finditer(comment_body):
        cmd = m.group(1)
        arg = m.group(2).strip()
        commands.append((cmd, arg))
    return commands


# ============================================================
# Command execution
# ============================================================

def execute_command(cmd, arg, wave_file, pr_number, revision_count):
    """Execute a single command. Returns (success, message)."""
    text = read_wave_file(wave_file)
    if text is None:
        return False, f"Wave file not found: {wave_file}"

    if cmd == "drop":
        new_text = drop_objective(text, arg)
        if new_text == text:
            return False, f"Objective {arg} not found in wave file"
        write_wave_file(wave_file, new_text)
        return True, f"Dropped objective {arg} and associated cards"

    elif cmd == "defer":
        new_text = defer_objective(text, arg)
        write_wave_file(wave_file, new_text)
        return True, f"Deferred objective {arg} to next wave"

    elif cmd == "add":
        new_text, new_obj = add_objective(text, arg)
        write_wave_file(wave_file, new_text)
        return True, f"Added new objective {new_obj}: {arg}"

    elif cmd == "answer":
        # Answer is recorded as a comment; planner picks it up on next revision
        return True, f"Answer recorded: {arg}"

    return False, f"Unknown command: !{cmd}"


def process_comment(pr_number, comment_body, comment_author):
    """Main entry: process a PR comment for !commands."""
    # 作者白名单（单向阀门）：非白名单作者的评论直接忽略
    allowed = _load_allowed_authors()
    if allowed and comment_author not in allowed:
        print(f"UNAUTHORIZED_COMMENT_AUTHOR: @{comment_author} not in whitelist "
              f"({sorted(allowed)})")
        return {"action": "skip", "reason": f"unauthorized comment author: {comment_author}"}

    commands = parse_commands(comment_body)
    if not commands:
        return {"action": "skip", "reason": "no commands found"}

    # Get PR info
    pr_info = get_pr_info(pr_number)
    if not pr_info:
        return {"action": "error", "reason": "could not fetch PR info"}

    if pr_info.get("state") != "OPEN":
        return {"action": "skip", "reason": "PR not open"}

    # Find wave file
    wave_file = find_wave_file(pr_number)
    if not wave_file:
        return {"action": "skip", "reason": "no wave file in PR diff"}

    # Check revision limit
    revision_count = count_revisions(pr_number)
    if revision_count >= MAX_REVISIONS:
        comment_on_pr(pr_number,
            f"⚠️ Revision limit reached ({MAX_REVISIONS} rounds). "
            f"Please Approve the current PR or manually edit the wave file.\n\n"
            f"Commands from @{comment_author} were not applied.")
        return {"action": "rejected", "reason": f"revision limit ({MAX_REVISIONS}) reached"}

    branch = pr_info.get("headRefName","")

    # Execute commands
    results = []
    any_success = False
    for cmd, arg in commands:
        success, msg = execute_command(cmd, arg, wave_file, pr_number, revision_count)
        results.append({"cmd": cmd, "arg": arg, "success": success, "message": msg})
        if success:
            any_success = True

    # Commit and force-push if any changes were made
    pushed = False
    if any_success:
        commit_msg = f"planner: revision round {revision_count + 1} per human feedback"
        pushed = commit_and_force_push(wave_file, branch, commit_msg)

    # Post result comment
    round_label = f"[revision-round-{revision_count + 1}]"
    summary = f"{round_label} Revision by @{comment_author} (round {revision_count + 1}/{MAX_REVISIONS})\n\n"
    for r in results:
        icon = "✓" if r["success"] else "✗"
        summary += f"- {icon} `!{r['cmd']} {r['arg']}`: {r['message']}\n"
    if pushed:
        summary += f"\nForce-pushed to `{branch}`. Planner will re-check and update."
    elif any_success:
        summary += f"\n⚠ Push failed — changes saved locally but not pushed."
    summary += f"\n\nRemaining revisions: {MAX_REVISIONS - revision_count - 1}"

    comment_on_pr(pr_number, summary)

    return {
        "action": "processed",
        "commands": len(commands),
        "results": results,
        "pushed": pushed,
        "revision_round": revision_count + 1
    }


# ============================================================
# CLI entry
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Process wave PR !commands")
    parser.add_argument("--pr", type=int, default=int(E.get("PR_NUMBER",0)),
                        help="PR number")
    parser.add_argument("--comment", default=E.get("COMMENT_BODY",""),
                        help="Comment body text")
    parser.add_argument("--author", default=E.get("COMMENT_AUTHOR",""),
                        help="Comment author login")
    args = parser.parse_args()

    if not args.pr or not args.comment:
        print("No PR number or comment body provided. Nothing to do.")
        return

    result = process_comment(args.pr, args.comment, args.author)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result.get("action") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
