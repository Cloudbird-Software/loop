#!/usr/bin/env python3
"""gate_verdict — VERDICT binding check.

For standard/critical tier cards with verify.required=true:
  1. A VERDICT JSON block must be present in a PR comment.
  2. VERDICT.head_sha must equal current PR HEAD SHA.
  3. All ACs must pass.

Trivial tier: skipped.
"""
import json, subprocess, sys, os, re

GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")
GH_TOKEN = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))


def gh_json(*args):
    env = dict(os.environ)
    if GH_TOKEN:
        env["GH_TOKEN"] = GH_TOKEN
    p = subprocess.run(["gh", *args], capture_output=True, text=True, env=env)
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


def get_pr_number():
    """Extract PR number from GITHUB_REF (refs/pull/123/merge)."""
    ref = os.environ.get("GITHUB_REF", "")
    parts = ref.split("/")
    if len(parts) >= 3 and parts[1] == "pull":
        return parts[2]
    # merge_group event uses GITHUB_REF differently; try event payload
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if event_path:
        try:
            ev = json.loads(open(event_path).read())
            if "pull_request" in ev:
                return str(ev["pull_request"]["number"])
        except Exception:
            pass
    return None


def get_card_from_pr(pr_num):
    """Read PR body, find Card: #N, fetch card issue, parse card JSON."""
    pr = gh_json("pr", "view", pr_num, "--json", "body")
    if not pr:
        return None
    body = pr.get("body", "")
    m = re.search(r"Card:\s*#(\d+)", body)
    if not m:
        return None
    issue = gh_json("issue", "view", m.group(1), "--json", "body")
    if not issue:
        return None
    issue_body = issue.get("body", "")
    marker = "```json loop"
    if marker not in issue_body:
        return None
    seg = issue_body.split(marker, 1)[1].split("```", 1)[0]
    try:
        return json.loads(seg)
    except json.JSONDecodeError:
        return None


def get_head_sha():
    """Get current HEAD commit SHA."""
    p = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return p.stdout.strip()


def find_verdict_in_comments(pr_num):
    """Search PR comments for a ```json verdict block."""
    comments = gh_json(
        "api",
        f"repos/{GITHUB_REPOSITORY}/issues/{pr_num}/comments",
        "--paginate",
    )
    if not comments or not isinstance(comments, list):
        return None
    marker = "```json verdict"
    for c in reversed(comments):  # most recent first
        body = c.get("body", "")
        if marker not in body:
            continue
        seg = body.split(marker, 1)[1].split("```", 1)[0]
        try:
            return json.loads(seg)
        except json.JSONDecodeError:
            continue
    return None


def validate_verdict(verdict, head_sha):
    """Validate VERDICT against required schema fields."""
    required = ["head_sha", "blind_phase_commit", "artifact_digest",
                "test_plan_version", "acs"]
    for field in required:
        if field not in verdict:
            return f"MISSING_FIELD: {field}"
    if not isinstance(verdict["acs"], list) or len(verdict["acs"]) == 0:
        return "ACS_EMPTY"
    for ac in verdict["acs"]:
        for f in ("id", "pass", "evidence"):
            if f not in ac:
                return f"AC_MISSING_FIELD: {f} in {ac.get('id', '?')}"
    if verdict["head_sha"] != head_sha:
        return (f"VERDICT_SHA_MISMATCH: verdict={verdict['head_sha'][:12]} "
                f"head={head_sha[:12]}")
    failed = [ac["id"] for ac in verdict["acs"] if not ac.get("pass")]
    if failed:
        return f"AC_FAILED: {', '.join(failed)}"
    return None


def main():
    pr_num = get_pr_number()
    if not pr_num:
        print("SKIP: cannot determine PR number")
        sys.exit(0)

    card = get_card_from_pr(pr_num)
    if not card:
        print("SKIP: no card linked to PR")
        sys.exit(0)

    tier = card.get("tier", "trivial")
    verify = card.get("verify", {})
    verify_required = verify.get("required", False) if isinstance(verify, dict) else False

    if tier == "trivial":
        print(f"SKIP (tier={tier})")
        sys.exit(0)

    if not verify_required:
        print(f"SKIP (verify.required=false, tier={tier})")
        sys.exit(0)

    head_sha = get_head_sha()
    verdict = find_verdict_in_comments(pr_num)

    if not verdict:
        print(f"FAIL: NO_VERDICT — tier={tier} requires a VERDICT comment "
              f"(post ```json verdict block via `loop verdict <file>`)")
        sys.exit(1)

    err = validate_verdict(verdict, head_sha)
    if err:
        print(f"FAIL: {err}")
        sys.exit(1)

    ac_count = len(verdict["acs"])
    print(f"OK (head_sha={head_sha[:12]}, acs={ac_count}, all pass)")


if __name__ == "__main__":
    main()
