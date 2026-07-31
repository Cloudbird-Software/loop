#!/usr/bin/env bash
# lenses/ci-security.sh — CI/workflow 静态安全检查（zizmor + pinact）（R11-8）。
#
# 审查裁决 R11-8：取代旧的 `zizmor --persona pedantic --format sarif . > ... || true` 假绿。
# 铁律（CHARTER N5）：工具缺失/崩溃 → 打印 LENS_NOT_EXECUTED 并非零退出，
# 绝不静默 SKIP（旧的 `|| true` 假绿不复现）。工具跑完才允许 exit 0。
# findings 不改变退出码——它们经 SARIF 上报 GitHub code scanning，并由
# .loop/scripts/sarif2evidence.py 转 evidence（WAVE-14 plumbing）。
#
# Evidence envelope: {"lens":"ci-security","shard":"S1",...,"findings":[...]}
set -euo pipefail

LENS="ci-security"
AUDIT_DIR=".loop/audit"
SARIF="$AUDIT_DIR/ci-security.sarif"
PINACT_OUT="$AUDIT_DIR/ci-security.pinact.txt"
EVIDENCE="$AUDIT_DIR/ci-security.evidence.json"
BASELINE="lenses/ci-security.baseline.yml"
SARIF2EVIDENCE=".loop/scripts/sarif2evidence.py"

mkdir -p "$AUDIT_DIR"

# ── zizmor：必需。缺失 → LENS_NOT_EXECUTED 非零退出 ──────────────────────
# zizmor 是 Python 包（pip install zizmor），不是 GitHub Action，故无 uses: 引用。
if ! command -v zizmor >/dev/null 2>&1; then
  echo "LENS_NOT_EXECUTED: zizmor (install: pip install zizmor)" >&2
  exit 1
fi
ZIZMOR_VERSION="$(zizmor --version 2>&1)"
echo "zizmor: $ZIZMOR_VERSION"

# --offline：强制离线审计，结果确定（不依赖 GH_TOKEN），与基线对齐。
# 工具崩溃（非零退出）由 set -e 直接红；findings 默认不影响退出码（zizmor 无 --fail-on）。
zizmor --offline --persona pedantic --format sarif . > "$SARIF"

# ── pinact：verify 模式（--check）。缺失 → LENS_NOT_EXECUTED 非零退出 ──────
# pinact 是 Go 二进制（pip 装不了）：优先用 PATH 上的；否则用 gh 从
# suzuki-shunsuke/pinact 下载（公开 release）。仍不可得 → LENS_NOT_EXECUTED。
PINACT_BIN=""
if command -v pinact >/dev/null 2>&1; then
  PINACT_BIN="$(command -v pinact)"
elif command -v gh >/dev/null 2>&1; then
  pdir="$(mktemp -d)"
  if gh release download v4.1.1 -R suzuki-shunsuke/pinact \
        -p 'pinact_linux_amd64.tar.gz' -D "$pdir" >/dev/null 2>&1 \
     && tar -xzf "$pdir/pinact_linux_amd64.tar.gz" -C "$pdir" >/dev/null 2>&1; then
    PINACT_BIN="$pdir/pinact"
  fi
fi
if [ -z "$PINACT_BIN" ]; then
  echo "LENS_NOT_EXECUTED: pinact (not on PATH; install: gh release download v4.1.1 -R suzuki-shunsuke/pinact -p pinact_linux_amd64.tar.gz)" >&2
  exit 1
fi
PINACT_VERSION="$("$PINACT_BIN" version 2>&1)"
echo "pinact: $PINACT_VERSION"

# pinact run -fix=false --no-api：离线语法校验所有 uses: 是否钉到 40 位 SHA。
# （--no-api 必须配合 -fix=false；纯 40 位 SHA 检查，不调 GitHub API，免 token。）
# 非零退出 = 发现未钉引用（findings，非工具失败）→ 记录到 $PINACT_OUT，不让镜头红
# （实际阻塞由 pr-ci.yml 的 actions-pinned gate 负责；此处仅采集证据）。
if ! "$PINACT_BIN" run -fix=false --no-api > "$PINACT_OUT" 2>&1; then
  echo "pinact: 发现未钉 SHA 的 action（见 $PINACT_OUT）" >&2
else
  echo "pinact: 所有 action 均钉到 40 位 SHA（verify OK）"
fi

# ── 基线过滤：抑制已知 findings；对已修复项发 STALE_BASELINE 警告 ──────────
# 读 baseline → 与 zizmor 结果比对：命中基线的 finding 从 SARIF 中移除（suppress）；
# 基线条目但 zizmor 不再报 → STALE_BASELINE 警告（警告，不红）。
python3 - "$SARIF" "$BASELINE" <<'PY'
import json, sys, pathlib
try:
    import yaml
except ImportError:
    print("ci-security: PyYAML not installed — baseline filter needs it "
          "(pip install PyYAML)", file=sys.stderr)
    sys.exit(1)

sarif_path, baseline_path = sys.argv[1], sys.argv[2]
sarif = json.loads(pathlib.Path(sarif_path).read_text(encoding="utf-8"))
bl = yaml.safe_load(pathlib.Path(baseline_path).read_text(encoding="utf-8")) or {}
entries = bl.get("baseline", []) if isinstance(bl, dict) else []


def loc_of(r):
    loc = r.get("locations", [{}])[0].get("physicalLocation", {})
    return (r.get("ruleId", "unknown"),
            loc.get("artifactLocation", {}).get("uri", ""))


total = suppressed = 0
entry_matched = [False] * len(entries)
for run in sarif.get("runs", []):
    kept = []
    for r in run.get("results", []):
        total += 1
        rid, path = loc_of(r)
        is_base = False
        for j, e in enumerate(entries):
            if e.get("rule_id") != rid:
                continue
            ep = e.get("path")
            if not ep or ep == path:
                is_base = True
                entry_matched[j] = True
                break
        if is_base:
            suppressed += 1
        else:
            kept.append(r)
    run["results"] = kept

stale = [e for j, e in enumerate(entries) if not entry_matched[j]]
for e in stale:
    print(f"STALE_BASELINE: rule_id={e.get('rule_id')} path={e.get('path', '*')} "
          f"— zizmor no longer reports this; remove from {baseline_path}")

pathlib.Path(sarif_path).write_text(
    json.dumps(sarif, indent=2), encoding="utf-8")
print(f"ci-security baseline: total={total} suppressed={suppressed} "
      f"remaining(new)={total - suppressed} stale_baseline={len(stale)}")
PY

# ── SARIF → evidence（WAVE-14 plumbing） ─────────────────────────────────
if [ ! -f "$SARIF2EVIDENCE" ]; then
  echo "LENS_NOT_EXECUTED: sarif2evidence.py (missing $SARIF2EVIDENCE)" >&2
  exit 1
fi
python3 "$SARIF2EVIDENCE" "$LENS" "$SARIF" > "$EVIDENCE"
echo "evidence: $EVIDENCE"

echo "ci-security lens: OK (tools ran; SARIF=$SARIF)"
