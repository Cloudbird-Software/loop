#!/usr/bin/env python3
"""gate_epoch — validate a PR working branch's epoch against the card's expected epoch.

Epoch fencing gate (W2-3):
  1. The card claims a lease whose ``epoch`` should equal ``attempt``.
  2. The working branch MUST follow the pattern ``<card_id>/e<epoch>``
     (loopd.domain.lease.branch_for), i.e. a ``/e<epoch>`` suffix.
  3. If the PR head branch's epoch != the card's expected epoch, the gate FAILs
     (exit 1) to prevent a stale/incorrect epoch claim from landing. When
     ``--close-on-fail`` is given it also auto-closes the PR via ``gh pr close``
     (a missing ``gh`` is a real error, not silently swallowed).

Usage:
    python3 gates/gate_epoch.py <expected_epoch> [branch] [--close-on-fail]

Input:
    argv[1]  expected_epoch — the card's expected epoch (int).
    argv[2]  branch — the PR head branch. If omitted, uses env ``GITHUB_HEAD_REF``.
    --close-on-fail — only when set, actually run ``gh pr close`` on epoch mismatch
                      (keeps local testing gh-free while staying honest in CI).

Exit codes:
    0 — branch is not an epoch branch (SKIP), or epoch matches.
    1 — epoch mismatch (or close-on-fail unrecoverable).
"""
import argparse
import os
import re
import subprocess
import sys

try:  # single-source when PYTHONPATH allows
    from loopd.domain.lease import is_epoch_branch
    _BRANCH_SRC = "loopd.domain.lease (single-source)"
except ImportError:
    # Standalone fallback so this gate remains runnable outside the package.
    _BRANCH_SRC = "local duplicate (loopd.domain.lease not importable)"
    _EPOCH_BRANCH_RE = re.compile(r"^(.+)/e(\d+)$")

    def is_epoch_branch(branch):
        if not isinstance(branch, str):
            return None
        m = _EPOCH_BRANCH_RE.fullmatch(branch)
        if not m:
            return None
        return int(m.group(2))


def get_pr_number():
    """Derive a PR number from CI refs (mirrors existing gates)."""
    ref = os.environ.get("GITHUB_REF", "") or os.environ.get("LOOP_CI_REF", "") or ""
    for pat in (r"refs/pull/(\d+)/", r"refs/pull/(\d+)$", r"merge-pr-(\d+)"):
        m = re.search(pat, ref)
        if m:
            return m.group(1)
    return None


def close_pr_on_fail(pr_num, branch):
    """Best-effort-but-not-silent PR auto-close. Missing ``gh`` is a real error."""
    import shutil
    if shutil.which("gh") is None:
        print("CLOSE_ERR: `gh` not on PATH; cannot auto-close PR "
              "(failing epoch is the real gate, but gh was requested via --close-on-fail)")
        return False
    if not pr_num:
        print("CLOSE_WARN: no PR number from CI refs; skipping `gh pr close`")
        return True
    p = subprocess.run(
        ["gh", "pr", "close", pr_num, "--comment",
         f"epoch fence violated: branch {branch} does not match card epoch"],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print(f"CLOSE_ERR: `gh pr close {pr_num}` failed: {p.stderr.strip()}")
        return False
    print(f"CLOSE_OK: auto-closed PR #{pr_num} (epoch violation)")
    return True


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("expected_epoch", nargs="?")
    parser.add_argument("branch", nargs="?")
    parser.add_argument("--close-on-fail", action="store_true", default=False)
    ns = parser.parse_args(argv)

    if ns.expected_epoch is None:
        print("FAIL: expected_epoch (argv[1]) is required")
        return 1
    try:
        expected = int(ns.expected_epoch)
    except ValueError:
        print(f"FAIL: expected_epoch not an int: {ns.expected_epoch!r}")
        return 1

    branch = ns.branch or os.environ.get("GITHUB_HEAD_REF")
    if not branch:
        print("FAIL: no branch given (argv[2]) and no GITHUB_HEAD_REF set")
        return 1

    branch_epoch = is_epoch_branch(branch)
    if branch_epoch is None:
        # Not an epoch branch: nothing to fence — treat as skip (pass).
        print(f"SKIP: branch {branch!r} is not an epoch branch (no /e<epoch> suffix)")
        return 0

    if branch_epoch != expected:
        print(f"FAIL: branch epoch mismatch — branch={branch!r} epoch={branch_epoch} "
              f"!= expected {expected} (source={_BRANCH_SRC})")
        if ns.close_on_fail:
            pr = get_pr_number()
            ok = close_pr_on_fail(pr, branch)
            if not ok and not pr:
                return 1  # requested close but couldn't do it reliably
        return 1

    print(f"OK: branch {branch!r} epoch {branch_epoch} == expected {expected} "
          f"(source={_BRANCH_SRC})")
    return 0


if __name__ == "__main__":
    sys.exit(main())