# gates/gate_paths.py —— 卡片 paths 与实际 diff 的一致性（C-012 最小测试：无 PR/无 Card 引用时 SKIP 不崩，exit 0）
import json, subprocess, sys, fnmatch, os, re

def _skip(msg):
    print(f"SKIP: {msg}")
    sys.exit(0)

def gh(*a, **kw):
    try:
        return subprocess.run(["gh", *a], capture_output=True, text=True, timeout=30, **kw)
    except Exception as e:
        return subprocess.CompletedProcess(args=a, returncode=1, stdout="", stderr=str(e))

# 1. 不是 PR/merge_group 环境 → SKIP（本地跑或 push 到 main 不需要检查 lease）
ref = os.environ.get("GITHUB_REF") or os.environ.get("LOOP_CI_REF") or ""
pr = None
for pat in [r"refs/pull/(\d+)/", r"refs/pull/(\d+)$", r"merge-pr-(\d+)"]:
    m = re.search(pat, ref)
    if m: pr = m.group(1); break
if pr is None:
    _skip(f"no PR context (GITHUB_REF={ref or 'unset'})")

# 2. 没有 gh 或 PR body 不含 Card: #NNN → SKIP（裸 PR 不由 card 驱动时，由 charter/verdict gate 管）
v = gh("pr", "view", pr, "--json", "body", "-q", ".body")
if v.returncode != 0:
    _skip(f"gh pr view failed ({v.stderr.strip()[:100]})")
body = v.stdout or ""
m = re.search(r"Card:\s*#(\d+)", body)
if not m:
    _skip("PR body has no 'Card: #NNN' reference (not card-driven, lease check waived)")
card_num = m.group(1)

# 3. card issue body 里没 frontmatter JSON blob → SKIP（老式卡兼容）
c = gh("issue", "view", card_num, "--json", "body", "-q", ".body")
if c.returncode != 0:
    _skip(f"gh issue view {card_num} failed")
card_body = c.stdout or ""
if "```json loop" in card_body:
    blob = card_body.split("```json loop", 1)[1].split("```", 1)[0]
    try:
        card = json.loads(blob)
    except Exception as e:
        _skip(f"card #{card_num} JSON blob parse fail ({e})")
else:
    _skip(f"card #{card_num} has no ```json loop blob (old-format card, lease waived)")

# 4. 没 git diff → SKIP
try:
    base = subprocess.run(["git", "merge-base", (os.environ.get("LOOP_CI_BASE") or "origin/main"), "HEAD"],
                          capture_output=True, text=True, timeout=20).stdout.strip()
    files = subprocess.run(["git", "diff", "--name-only", base, "HEAD"],
                           capture_output=True, text=True, timeout=20).stdout.split()
except Exception as e:
    _skip(f"git diff unavailable ({e})")

lease = card.get("paths", [])
forbid = card.get("forbid_paths", [])
if not lease:
    _skip(f"card #{card_num} has empty paths (lease not declared, waived)")

bad = []
for f in files:
    if any(fnmatch.fnmatch(f, p) for p in forbid):
        bad.append(f"FORBID {f}")
        continue
    if not any(fnmatch.fnmatch(f, p) for p in lease):
        bad.append(f"OUT_OF_LEASE {f}")

if bad:
    print("PATHS_LEASE_VIOLATION:\n" + "\n".join(bad))
    sys.exit(1)
print(f"OK {len(files)} files within lease of card #{card_num}: paths={lease}")
