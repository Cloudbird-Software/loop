#!/usr/bin/env python3
"""gate_testown — Test ownership gate.

If the PR changes any file under tests/acceptance/**, the PR must carry
the `test-change-approved` label. Otherwise → red.

tests/acceptance/** is a CODEOWNERS-protected sensitive path; only humans
may modify acceptance tests, and any such change requires explicit approval.
"""
import json, subprocess, sys, os, re, fnmatch

GH_TOKEN = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
ACCEPTANCE_PATTERN = "tests/acceptance/**"
REQUIRED_LABEL = "test-change-approved"


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
    ref = os.environ.get("GITHUB_REF", "")
    parts = ref.split("/")
    if len(parts) >= 3 and parts[1] == "pull":
        return parts[2]
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if event_path:
        try:
            ev = json.loads(open(event_path).read())
            if "pull_request" in ev:
                return str(ev["pull_request"]["number"])
        except Exception:
            pass
    return None


def get_changed_files():
    """Get list of changed files in the PR."""
    base = os.environ.get("GITHUB_BASE_REF", "main")
    # Use merge-base for accurate diff
    p = subprocess.run(
        ["git", "merge-base", f"origin/{base}", "HEAD"],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        p = subprocess.run(
            ["git", "rev-parse", f"origin/{base}"],
            capture_output=True, text=True,
        )
    base_sha = p.stdout.strip()
    if not base_sha:
        base_sha = "HEAD~1"
    p = subprocess.run(
        ["git", "diff", "--name-only", base_sha, "HEAD"],
        capture_output=True, text=True,
    )
    return [f for f in p.stdout.strip().split("\n") if f]


def get_pr_labels(pr_num):
    """Get labels on the PR."""
    pr = gh_json("pr", "view", pr_num, "--json", "labels")
    if not pr:
        return []
    labels = pr.get("labels", [])
    if isinstance(labels, list):
        return [l.get("name", "") if isinstance(l, dict) else str(l) for l in labels]
    return []


def main():
    pr_num = get_pr_number()
    if not pr_num:
        print("SKIP: cannot determine PR number")
        sys.exit(0)

    files = get_changed_files()
    # Check if any changed file matches tests/acceptance/**
    acceptance_changes = [
        f for f in files
        if fnmatch.fnmatch(f, ACCEPTANCE_PATTERN)
        or fnmatch.fnmatch(f, "tests/acceptance/*")
        or f.startswith("tests/acceptance/")
    ]

    if not acceptance_changes:
        print("OK (no acceptance test changes)")
        sys.exit(0)

    labels = get_pr_labels(pr_num)
    if REQUIRED_LABEL not in labels:
        print(f"FAIL: ACCEPTANCE_TEST_CHANGED without '{REQUIRED_LABEL}' label")
        print(f"  Changed acceptance files:")
        for f in acceptance_changes:
            print(f"    - {f}")
        print(f"  Required: add '{REQUIRED_LABEL}' label (see docs/test-change-approved流程.md)")
        sys.exit(1)

    print(f"OK (acceptance test changes approved via '{REQUIRED_LABEL}' label)")
    print(f"  Changed: {', '.join(acceptance_changes)}")
    sys.exit(0)


if __name__ == "__main__":
    main()
