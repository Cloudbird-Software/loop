#!/usr/bin/env python3
"""gate_diffsize — 按 Card tier 校验 PR diff 行数预算。"""
import json, os, re, subprocess, sys

DEFAULT_LIMITS = {"trivial": 300, "standard": 600, "critical": 400}
LOCK_NAMES = {"package-lock.json", "poetry.lock", "go.sum"}


def run(*cmd): return subprocess.run(cmd, capture_output=True, text=True)

def gh_json(*args):
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    if p.returncode != 0: return None
    try: return json.loads(p.stdout)
    except json.JSONDecodeError: return None


def get_pr_number():
    parts = os.environ.get("GITHUB_REF", "").split("/")
    if len(parts) >= 3 and parts[1] == "pull": return parts[2]
    ep = os.environ.get("GITHUB_EVENT_PATH", "")
    if ep:
        try:
            ev = json.loads(open(ep).read())
            if "pull_request" in ev: return str(ev["pull_request"]["number"])
        except Exception:
            pass
    return None


def extract_card(body):
    marker = "```json loop"
    if marker not in (body or ""): return None
    try: return json.loads(body.split(marker, 1)[1].split("```", 1)[0])
    except json.JSONDecodeError: return None


def get_card_from_pr(pr_num):
    pr = gh_json("pr", "view", pr_num, "--json", "body")
    if not pr: return None
    m = re.search(r"Card:\s*#(\d+)", pr.get("body", ""))
    if not m: return None
    issue = gh_json("issue", "view", m.group(1), "--json", "body")
    return extract_card(issue.get("body", "")) if issue else None


def load_limits(path="policy.yml"):
    try:
        import yaml
        return (yaml.safe_load(open(path)) or {}).get("execute", {}).get("max_diff_lines", DEFAULT_LIMITS)
    except Exception:
        return DEFAULT_LIMITS


def resolve_base(pr_num=None):
    base = os.environ.get("GITHUB_BASE_REF")
    if base:
        mb = run("git", "merge-base", f"origin/{base}", "HEAD").stdout.strip()
        if mb: return mb
        rv = run("git", "rev-parse", f"origin/{base}")
        if rv.returncode == 0 and rv.stdout.strip(): return rv.stdout.strip()
    if pr_num:
        pr = gh_json("pr", "view", pr_num, "--json", "baseRefOid") or {}
        if pr.get("baseRefOid"): return pr["baseRefOid"]
    return os.environ.get("LOOP_CI_BASE", "HEAD~1")


def is_excluded(path):
    name = os.path.basename(path)
    return path.endswith(".lock") or name in LOCK_NAMES


def count_requirements_hash_diff(base, head, path):
    p = run("git", "diff", f"{base}..{head}", "--", path)
    total = 0
    for line in p.stdout.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")): continue
        text = line[1:].strip()
        if text.startswith("--hash=") or " --hash=" in text: continue
        total += 1
    return total


def diff_lines(base, head="HEAD"):
    p = run("git", "diff", "--numstat", f"{base}..{head}")
    total = 0
    for line in p.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or is_excluded(parts[2]): continue
        if os.path.basename(parts[2]) == "requirements.txt":
            total += count_requirements_hash_diff(base, head, parts[2]); continue
        try: total += int(parts[0]) + int(parts[1])
        except ValueError: pass
    return total


def main():
    pr_num = get_pr_number()
    if not pr_num:
        print("SKIP: cannot determine PR number"); sys.exit(0)
    card = get_card_from_pr(pr_num)
    if not card:
        print("SKIP: no card linked to PR"); sys.exit(0)
    tier = card.get("tier", "standard")
    limit = int(load_limits().get(tier, DEFAULT_LIMITS.get(tier, 600)))
    count = diff_lines(resolve_base(pr_num), os.environ.get("GITHUB_SHA", "HEAD"))
    if count > limit:
        print(f"FAIL: DIFF_TOO_LARGE tier={tier} lines={count} limit={limit}"); sys.exit(1)
    print(f"OK diff size {count}/{limit} lines (tier={tier})")


if __name__ == "__main__":
    main()
