#!/usr/bin/env python3
"""gate_charter — 校验 Card charter 引用必须落在 CHARTER.md 中。"""
import json, os, re, subprocess, sys

GH_TOKEN = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))


def gh_json(*args):
    env = dict(os.environ)
    if GH_TOKEN: env["GH_TOKEN"] = GH_TOKEN
    p = subprocess.run(["gh", *args], capture_output=True, text=True, env=env)
    if p.returncode != 0: return None
    try: return json.loads(p.stdout)
    except json.JSONDecodeError: return None


def get_pr_number():
    ref = os.environ.get("GITHUB_REF", "")
    parts = ref.split("/")
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


def load_charter_ids(path="CHARTER.md"):
    ids = set()
    if not os.path.exists(path): return ids, False
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^([GNUQ]\d+)\s", line)
        if m: ids.add(m.group(1))
    return ids, True


def validate_charter(card, ids, charter_exists):
    refs = card.get("charter") if isinstance(card, dict) else None
    if not refs: return ["MISSING_CHARTER"]
    if isinstance(refs, str): refs = [refs]
    if not isinstance(refs, list) or not all(str(r).strip() for r in refs):
        return ["EMPTY_CHARTER_REF"]
    refs = [str(r).strip() for r in refs]
    if not charter_exists:
        return [] if refs == ["G0"] else [f"UNKNOWN_CHARTER {r} (CHARTER.md missing)" for r in refs]
    return [f"UNKNOWN_CHARTER {r}" for r in refs if r not in ids]


def main():
    pr_num = get_pr_number()
    if not pr_num:
        print("SKIP: cannot determine PR number"); sys.exit(0)
    card = get_card_from_pr(pr_num)
    if not card:
        print("SKIP: no card linked to PR"); sys.exit(0)
    ids, exists = load_charter_ids()
    bad = validate_charter(card, ids, exists)
    if bad:
        print("FAIL: CHARTER_VIOLATION\n" + "\n".join(bad)); sys.exit(1)
    print(f"OK charter refs valid: {card.get('charter')}")


if __name__ == "__main__":
    main()
