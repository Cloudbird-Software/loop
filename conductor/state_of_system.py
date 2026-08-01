#!/usr/bin/env python3
"""conductor/state_of_system.py — 生成 loop 控制面真实系统状态（W0-1）。

设计原则（CHARTER G3 / N11 不撒谎）：
  - 只报告可观测的事实；探不到的字段一律标 "unknown"，绝不假绿。
  - gh / 网络不可达时降级为 "unknown"，不编造数字。
  - --verify：能无异常产出一份状态报告即 exit 0（AC-1）；崩溃则原样冒泡非 0。

报告内容（均为可观测事实，best-effort 采集）：
  - 仓库根 / 生成时间
  - policy.yml：freeze.all、gates.profiles.default 数量
  - products.yml：注册产品仓列表
  - .loop/liveness.yml：ticks 期望周期登记数
  - gates/：实际存在的 gate 文件
  - gh 可达性 + open issues 计数（best-effort，不可达即 unknown）

可导入：核心逻辑封装为 gather_state() / render_report()，main() 为入口。
"""
import datetime
import json
import os
import subprocess
import sys

# W0-1 sys.path 修复：与 conductor/tick.py、conductor/audit.py 同风格，使
# `python conductor/state_of_system.py` 直跑与 `python -m conductor.state_of_system`
# 两种模式下 conductor.* 包导入都可用（直跑时 sys.path[0] 是 conductor/ 而非仓库根）。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _now_iso():
    """aware UTC ISO 时间戳（与 conductor/audit.py _now_iso 同风格）。"""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _load_yaml(path):
    """读 YAML 文件；PyYAML 不可用 / 文件缺失 / 解析失败均返回 None。

    返回 None 时由调用方标 unknown 或 missing（不假绿）。best-effort，不抛异常。
    """
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return None
    except ImportError:
        return None
    except Exception:
        return None


def _read_policy(repo_root):
    """读 policy.yml 的可观测字段。文件缺失/不可读 → present=False（诚实）。"""
    path = os.path.join(repo_root, "policy.yml")
    data = _load_yaml(path)
    if data is None:
        return {"present": False, "freeze_all": "unknown",
                "gates_default_count": "unknown"}
    freeze = data.get("freeze", {}) or {}
    profiles = (data.get("gates", {}) or {}).get("profiles", {}) or {}
    default_gates = profiles.get("default", []) or []
    return {
        "present": True,
        "freeze_all": bool(freeze.get("all", False)),
        "gates_default_count": len(default_gates),
    }


def _read_products(repo_root):
    """读 products.yml 的注册产品列表。"""
    path = os.path.join(repo_root, "products.yml")
    data = _load_yaml(path)
    if data is None:
        return {"present": False, "products": []}
    prods = data.get("products", []) or []
    names = [
        p.get("name", "?") + " (" + p.get("repo", "?") + ")"
        for p in prods if isinstance(p, dict)
    ]
    return {"present": True, "products": names}


def _read_liveness(repo_root):
    """读 .loop/liveness.yml 的 ticks 登记数。"""
    path = os.path.join(repo_root, ".loop", "liveness.yml")
    data = _load_yaml(path)
    if data is None:
        return {"present": False, "ticks_count": "unknown"}
    ticks = data.get("ticks", []) or []
    return {"present": True, "ticks_count": len(ticks)}


def _list_gates(repo_root):
    """枚举 gates/ 下实际存在的 gate_*.py 文件。"""
    gdir = os.path.join(repo_root, "gates")
    if not os.path.isdir(gdir):
        return {"present": False, "gates": [], "count": 0}
    files = sorted(
        f for f in os.listdir(gdir)
        if f.startswith("gate_") and f.endswith(".py")
    )
    return {"present": True, "gates": files, "count": len(files)}


def _gh_available():
    """探测 gh CLI 是否可用；best-effort，不抛异常。"""
    try:
        p = subprocess.run(
            ["gh", "--version"], capture_output=True, text=True, timeout=10,
        )
        return p.returncode == 0
    except Exception:
        return False


def _resolve_query_repo():
    """从环境变量解析查询 open issues 用的 <ORG>/<REPO>；不可解析返回 None。"""
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo and "/" in repo:
        return repo
    # LOOP_REPO 可能只是 repo 名，需拼 org
    repo_name = os.environ.get("LOOP_REPO", "").strip()
    if not repo_name:
        return None
    if "/" in repo_name:
        return repo_name
    org = os.environ.get("GITHUB_REPOSITORY_OWNER", "").strip() or os.environ.get("LOOP_ORG", "").strip()
    return f"{org}/{repo_name}" if org else None


def _count_open_issues(repo):
    """best-effort 统计 open issue 数；失败返回 'unknown'。"""
    if not repo:
        return "unknown (no repo resolved)"
    try:
        p = subprocess.run(
            ["gh", "issue", "list", "-R", repo, "--state", "open",
             "--limit", "200", "--json", "number"],
            capture_output=True, text=True, timeout=30,
        )
        if p.returncode != 0:
            return "unknown (gh issue list failed)"
        items = json.loads(p.stdout or "[]")
        return len(items) if isinstance(items, list) else "unknown (bad json)"
    except Exception:
        return "unknown (gh unavailable)"


def gather_state(repo_root=None):
    """采集系统真实状态，返回 dict。所有不可观测字段标 unknown（不假绿，G3/N11）。"""
    root = repo_root or _REPO_ROOT
    state = {
        "generated_at": _now_iso(),
        "repo_root": root,
        "policy": _read_policy(root),
        "products": _read_products(root),
        "liveness": _read_liveness(root),
        "gates": _list_gates(root),
    }
    gh_ok = _gh_available()
    state["gh_available"] = gh_ok
    if gh_ok:
        state["open_issues"] = _count_open_issues(_resolve_query_repo())
    else:
        state["open_issues"] = "unknown (gh unavailable)"
    return state


def render_report(state):
    """把 state dict 渲染为人类可读文本。"""
    lines = []
    lines.append("=== loop control-plane state ===")
    lines.append(f"generated_at: {state['generated_at']}")
    lines.append(f"repo_root: {state['repo_root']}")
    lines.append("")

    pol = state["policy"]
    if pol["present"]:
        lines.append(
            f"policy.yml: present (freeze.all={pol['freeze_all']}, "
            f"gates.default count={pol['gates_default_count']})"
        )
    else:
        lines.append("policy.yml: missing or unreadable (freeze.all=unknown)")

    prods = state["products"]
    if prods["present"]:
        lines.append(f"products.yml: present ({len(prods['products'])} registered)")
        for name in prods["products"]:
            lines.append(f"  - {name}")
    else:
        lines.append("products.yml: missing or unreadable")

    live = state["liveness"]
    if live["present"]:
        lines.append(f"liveness.yml: present (ticks={live['ticks_count']})")
    else:
        lines.append("liveness.yml: missing or unreadable (ticks=unknown)")

    g = state["gates"]
    if g["present"]:
        lines.append(f"gates/: present ({g['count']} gate files)")
        for fname in g["gates"]:
            lines.append(f"  - {fname}")
    else:
        lines.append("gates/: missing")

    lines.append(f"gh available: {state['gh_available']}")
    lines.append(f"open issues: {state['open_issues']}")
    lines.append("")
    lines.append("honesty note: 探不到的字段标 unknown，不假绿（CHARTER G3/N11）。")
    return "\n".join(lines)


def main(argv=None):
    """入口：采集状态 → 打印报告 → exit 0。

    --verify：能无异常产出报告即 exit 0（AC-1）；若采集过程崩溃则原样冒泡非 0
    （不吞退出码，N11）。
    """
    args = list(argv) if argv is not None else sys.argv[1:]
    state = gather_state()
    print(render_report(state))
    # --verify 与默认均 exit 0（报告成功产出即满足 AC-1）。
    if "--verify" in args:
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
