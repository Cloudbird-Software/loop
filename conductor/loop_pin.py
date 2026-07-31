#!/usr/bin/env python3
"""conductor/loop_pin.py — 统一的 loop pin 解析器（R13-6）。

三方共用同一解析实现，避免出现三份平行解析：
  - conductor/upgrade_ring.py（第 8 环升级）
  - gates/gate_conformance.py（合规门禁检查 1/2/6）
  - .github/workflows/template-sync.yml（种子文件扇出）

功能：
  - parse_loop_yml(path) → 解析 LOOP.yml，返回 {version, sha, max_lag_tags, max_lag_days, ...}
  - parse_upstream_loop(path) → 从 UPSTREAM.yaml 找 Cloudbird-Software/loop 条目
  - validate_pin(loop_yml, upstream_item) → 校验 pin 一致性（LOOP.yml.sha == UPSTREAM.yaml pin SHA）
  - fetch_loop_tags() → 用 gh api 拉 loop 仓 tag 列表
  - compute_lag(pin_sha, tags) → 计算落后 tag 数和天数
  - suggest_bump(current_pin, latest_tag) → 生成 bump PR 需要的变更集
"""
import json
import os
import re
import subprocess
import sys
import datetime

E = os.environ

LOOP_REPO_DEFAULT = "Cloudbird-Software/loop"


def load_yaml(path):
    """安全加载 YAML 文件。"""
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        print("ERROR: PyYAML not installed", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError:
        return {}


def parse_loop_yml(path="LOOP.yml"):
    """解析 LOOP.yml，返回 loop pin 信息。"""
    data = load_yaml(path)
    loop = data.get("loop", {}) if isinstance(data, dict) else {}
    return {
        "repo": loop.get("repo", LOOP_REPO_DEFAULT),
        "version": str(loop.get("version", "")),
        "sha": str(loop.get("sha", "")),
        "max_lag_tags": int(loop.get("max_lag_tags", 2)),
        "max_lag_days": int(loop.get("max_lag_days", 30)),
    }


def parse_upstream_loop(path="UPSTREAM.yaml"):
    """从 UPSTREAM.yaml 找 Cloudbird-Software/loop 条目。"""
    data = load_yaml(path)
    for item in data.get("items", []):
        name = str(item.get("name", ""))
        if name.lower() == LOOP_REPO_DEFAULT.lower():
            return item
    return None


def validate_pin(loop_yml_pin, upstream_item):
    """校验 LOOP.yml 和 UPSTREAM.yaml 中的 loop pin 一致性。

    返回 (is_valid, errors list)。
    """
    errors = []
    if not upstream_item:
        errors.append("UPSTREAM.yaml 中未找到 Cloudbird-Software/loop 条目")
        return False, errors

    # UPSTREAM.yaml 的 pin 格式："<tag>@<sha>" 或单独的 sha
    up_pin = str(upstream_item.get("pin", ""))
    up_sha = ""
    up_tag = ""
    if "@" in up_pin:
        up_tag, up_sha = up_pin.rsplit("@", 1)
    else:
        up_sha = up_pin

    loop_sha = loop_yml_pin.get("sha", "")
    loop_version = loop_yml_pin.get("version", "")

    if not re.fullmatch(r"[0-9a-f]{40}", loop_sha):
        errors.append(f"LOOP.yml loop.sha 不是 40 位十六进制: {loop_sha}")

    if not re.fullmatch(r"[0-9a-f]{40}", up_sha):
        errors.append(f"UPSTREAM.yaml pin 的 SHA 不是 40 位十六进制: {up_pin}")

    if loop_sha and up_sha and loop_sha != up_sha:
        errors.append(f"SHA 不一致: LOOP.yml={loop_sha[:12]}... UPSTREAM.yaml={up_sha[:12]}...")

    if loop_version and up_tag and loop_version != up_tag:
        errors.append(f"tag 不一致: LOOP.yml={loop_version} UPSTREAM.yaml={up_tag}")

    return len(errors) == 0, errors


def gh_api(endpoint, repo=None):
    """调用 gh api，返回 JSON 或 None。"""
    repo = repo or LOOP_REPO_DEFAULT
    r = subprocess.run(
        ["gh", "api", f"/repos/{repo}/{endpoint}", "--paginate"],
        capture_output=True, text=True, timeout=60
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def fetch_loop_tags(repo=None):
    """拉 loop 仓的 tag 列表，返回 [{name, commit: {sha, ...}}, ...]。"""
    data = gh_api("tags", repo=repo)
    if not isinstance(data, list):
        return []
    return data


def fetch_commit_info(sha, repo=None):
    """拉 commit 信息，返回 {sha, commit: {author: {date}, ...}, ...} 或 None。"""
    return gh_api(f"commits/{sha}", repo=repo)


def compute_lag(pin_sha, tags, repo=None):
    """计算 pin_sha 落后主干多少个 tag 和多少天。

    返回 (lag_tags, lag_days, latest_tag, latest_tag_date)。
    """
    if not tags:
        return (0, 0, None, None)

    # 找 pin_sha 在 tag 列表中的位置
    lag_tags = 0
    pin_found = False
    latest_tag = tags[0] if tags else None
    latest_tag_date = None

    for i, tag in enumerate(tags):
        tag_sha = tag.get("commit", {}).get("sha", "")
        if tag_sha == pin_sha:
            pin_found = True
            lag_tags = i
            break

    if not pin_found:
        # pin SHA 不在 tag 列表中（可能是分支 commit），算落后全部 tag
        lag_tags = len(tags)

    # 获取 pin commit 日期和最新 tag 日期
    pin_commit = fetch_commit_info(pin_sha, repo=repo)
    latest_commit = fetch_commit_info(latest_tag["commit"]["sha"], repo=repo) if latest_tag else None

    pin_date = None
    latest_date = None
    if pin_commit:
        date_str = pin_commit.get("commit", {}).get("author", {}).get("date", "")
        pin_date = _parse_iso(date_str)
    if latest_commit:
        date_str = latest_commit.get("commit", {}).get("author", {}).get("date", "")
        latest_date = _parse_iso(date_str)

    lag_days = 0
    if pin_date and latest_date:
        lag_days = (latest_date - pin_date).days

    return (lag_tags, lag_days, latest_tag.get("name") if latest_tag else None, latest_date)


def _parse_iso(s):
    s = (s or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except ValueError:
        return None


def suggest_bump(current_pin, latest_tag_info):
    """生成 bump PR 需要的变更集。

    返回 {
        "files": [
            {"path": "LOOP.yml", "old": ..., "new": ...},
            {"path": "UPSTREAM.yaml", "old": ..., "new": ...},
            {"path": ".github/workflows/loop-ci.yml", "old_sha": ..., "new_sha": ...},
            ...
        ],
        "new_version": ...,
        "new_sha": ...,
    }
    """
    new_tag = latest_tag_info.get("name", "")
    new_sha = latest_tag_info.get("commit", {}).get("sha", "")

    return {
        "files": [
            {"path": "LOOP.yml", "field": "loop.version", "old": current_pin.get("version", ""), "new": new_tag},
            {"path": "LOOP.yml", "field": "loop.sha", "old": current_pin.get("sha", ""), "new": new_sha},
            {"path": "UPSTREAM.yaml", "field": "pin", "old": f'{current_pin.get("version","")}@{current_pin.get("sha","")}', "new": f"{new_tag}@{new_sha}"},
            {"path": ".github/workflows/loop-ci.yml", "old_sha": current_pin.get("sha", ""), "new_sha": new_sha},
            {"path": ".github/workflows/loop-gates.yml", "old_sha": current_pin.get("sha", ""), "new_sha": new_sha},
            {"path": ".github/workflows/loop-review.yml", "old_sha": current_pin.get("sha", ""), "new_sha": new_sha},
        ],
        "new_version": new_tag,
        "new_sha": new_sha,
    }


def main():
    """CLI 入口：解析并打印 loop pin 状态。"""
    import argparse
    ap = argparse.ArgumentParser(description="loop pin 解析器（R13-6）")
    ap.add_argument("--loop-yml", default="LOOP.yml", help="LOOP.yml 路径")
    ap.add_argument("--upstream", default="UPSTREAM.yaml", help="UPSTREAM.yaml 路径")
    ap.add_argument("--check-lag", action="store_true", help="检查 pin 新鲜度")
    ap.add_argument("--check-consistency", action="store_true", help="检查 LOOP.yml 与 UPSTREAM.yaml 一致性")
    args = ap.parse_args()

    pin = parse_loop_yml(args.loop_yml)
    print(f"LOOP.yml pin: version={pin['version']} sha={pin['sha'][:12]}... max_lag_tags={pin['max_lag_tags']} max_lag_days={pin['max_lag_days']}")

    if args.check_consistency:
        up_item = parse_upstream_loop(args.upstream)
        if up_item:
            print(f"UPSTREAM.yaml pin: {up_item.get('pin', '?')}")
        else:
            print("UPSTREAM.yaml: loop 条目未找到")
        valid, errors = validate_pin(pin, up_item)
        if valid:
            print("CONSISTENCY: OK")
        else:
            for e in errors:
                print(f"CONSISTENCY: FAIL — {e}")

    if args.check_lag:
        tags = fetch_loop_tags(pin["repo"])
        lag_tags, lag_days, latest_tag, latest_date = compute_lag(pin["sha"], tags, pin["repo"])
        print(f"LAG: tags={lag_tags} days={lag_days} latest_tag={latest_tag}")
        if lag_tags > pin["max_lag_tags"]:
            print(f"STALE: 落后 {lag_tags} 个 tag > max_lag_tags({pin['max_lag_tags']})")
        elif lag_days > pin["max_lag_days"]:
            print(f"STALE: 落后 {lag_days} 天 > max_lag_days({pin['max_lag_days']})")
        else:
            print("FRESH: pin 在新鲜窗口内")


if __name__ == "__main__":
    main()
