#!/usr/bin/env python3
"""E包 B 类缺陷修复：materialize_cards.py
把 /workspace/cards/ 下 C-V-F 所有 markdown 卡物化成 product-x 的 GitHub issue。
每张卡 issue 含：
  - title = "[{type}] {id} — {title}"  （type ∈ Card|Verify|Finding）
  - labels = loop,type-{type},role-{role},tier-{tier},status-{status},ready-{ready|not},claimed,depends
  - body   = 原文 markdown 全文，末尾额外附 ```json loop  <frontmatter>  ``` blob
             （给 tick.py 和 gate_paths 读）
  - 幂等：先 gh issue list -R Cloudbird-Software/product-x --search 'id: C-001'，若已存在同名 issue 则跳过
"""
import json, re, os, subprocess, pathlib, sys, time

REPO = "Cloudbird-Software/product-x"
CARDS_DIR = pathlib.Path("/workspace/cards")
STATE_COLOR = {"done": "0e8a16", "pending": "ededed", "in_progress": "fbca04",
               "blocked": "b60205", "claimed": "f9d0c4", "ready": "c2e0c6"}


def gh(*args, check=False):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        print("GH ERR:", r.args, "stderr=", r.stderr[:500])
        r.check_returncode()
    return r


def ensure_labels(desired):
    """批量创建缺失的 labels（幂等）。desired = {name: color_hex}"""
    existing = {}
    p = gh("label", "list", "-R", REPO, "--json", "name,color", "--limit", "200")
    try:
        for it in json.loads(p.stdout or "[]"):
            existing[it["name"]] = it.get("color","")
    except Exception:
        pass
    for name, color in desired.items():
        if name in existing: continue
        r = gh("label", "create", "-R", REPO, name, "--color", color,
               "-d", f"loop card system: {name}", check=False)
        print(f"  [label] +{name} #{color}  rc={r.returncode}")


def parse_frontmatter(md_text):
    """解析卡片第一块 ```yaml ... ``` 作为 frontmatter，返回 dict。"""
    m = re.match(r"^#\s+[^\n]+\s*\n```yaml\s*\n(.*?)\n```\s*\n", md_text, re.S)
    if not m:
        return {}
    yaml_block = m.group(1)
    out = {}
    key, cur_lines = None, []
    def commit():
        if key is None: return
        v = "\n".join(cur_lines).strip()
        # 尝试 list / bool / 数字，失败就 str
        if v.startswith("[") and v.endswith("]"):
            try: out[key] = json.loads(v); return
            except Exception: pass
        # yaml 列表：以 "- " 开头多行
        if all(l.startswith("- ") for l in cur_lines if l.strip()):
            out[key] = [re.sub(r"^-\s*", "", l).strip() for l in cur_lines if l.strip()]
            return
        # bool
        if v.lower() in ("true","false"): out[key] = v.lower()=="true"; return
        if v.isdigit(): out[key] = int(v); return
        out[key] = v
    for raw in yaml_block.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith(" ") or line.startswith("\t"):
            cur_lines.append(line.strip())
        else:
            commit()
            if ":" in line:
                k, v = line.split(":", 1)
                key = k.strip()
                cur_lines = [v.strip()]
            else:
                key, cur_lines = None, []
    commit()
    return out


def issue_exists(card_id):
    """按 title prefix + card_id 精确查（幂等）。返回 issue number or None。"""
    q = f'{card_id} in:title repo:{REPO} is:issue'
    p = gh("issue", "list", "-R", REPO, "--search", q, "--json", "number,title", "--limit", "20")
    try:
        items = json.loads(p.stdout or "[]")
    except Exception:
        return None
    for it in items:
        if re.search(rf'\b{re.escape(card_id)}\b', it.get("title","")):
            return it["number"]
    return None


def build_labels(fm, card_id):
    type_map = {"Card": "Card", "Verify": "Verify", "Finding": "Finding"}
    ctype = type_map.get(fm.get("type","Card"), "Card")
    labels = ["loop", f"type-{ctype}"]
    if fm.get("role"): labels.append(f"role-{fm['role']}")
    if fm.get("tier"): labels.append(f"tier-{fm['tier']}")
    st = fm.get("status") or "pending"
    labels.append(f"status-{st}")
    if fm.get("ready"):
        labels.append("ready")
    if st in ("claimed","in_progress"):
        labels.append("claimed")
    if fm.get("depends_on"):
        labels.append("depends")
    return [l for l in labels if len(l) <= 50]


def build_body(md_text, fm, card_id):
    blob = json.dumps(fm, ensure_ascii=False, indent=2, sort_keys=True)
    return md_text.rstrip() + f"\n\n---\n\n```json loop\n{blob}\n```\n"


def main():
    # 1. 准备 labels
    label_spec = {
        "loop": "1f6feb",
        "type-Card": "1d76db", "type-Verify": "8458e7", "type-Finding": "c090ff",
        "role-impl": "0075ca", "role-verify": "7057ff", "role-auditor": "5319e7",
        "role-planner": "d876e3", "role-incident": "b60205",
        "tier-critical": "b60205", "tier-standard": "f9d0c4", "tier-trivial": "c5def5",
        "status-done": "0e8a16", "status-pending": "ededed",
        "status-in_progress": "fbca04", "status-blocked": "d93f0b",
        "status-claimed": "fbca04",
        "ready": "c2e0c6", "claimed": "fbca04", "depends": "bfd4f2",
        "verified": "0e8a16", "verdict-pass": "0e8a16", "verdict-fail": "d93f0b",
        "incident": "b60205", "finding": "c090ff",
        "hotfix": "ff9f1c", "zombie": "9f9f9f",
    }
    print("=== Step 1: ensure labels ===")
    ensure_labels(label_spec)

    # 2. 扫 cards/*.md，排除 README WORKFLOW INDEX
    pattern = re.compile(r"^(C|V|F|W|G|I|R)-\d+")
    files = sorted([p for p in CARDS_DIR.glob("*.md") if pattern.match(p.stem)])
    print(f"=== Step 2: found {len(files)} cards ===")

    # 3. 逐个物化
    created, skipped, errs = [], [], []
    for fp in files:
        card_id = fp.stem
        md = fp.read_text(encoding="utf-8")
        fm = parse_frontmatter(md)
        fm.setdefault("id", card_id)
        fm.setdefault("type", "Card" if card_id.startswith("C") else
                              "Verify" if card_id.startswith("V") else
                              "Finding" if card_id.startswith("F") else "Card")
        fm.setdefault("title", re.match(r"^#\s+(.+)$", md, re.M).group(1) if re.search(r"^#", md, re.M) else card_id)
        status = fm.get("status","pending")
        tier = fm.get("tier","standard")

        # title: "[{type}] {id} — {short}" 保持 GH 搜索一致
        title = f"[{fm['type']}] {card_id} — {fm.get('title', card_id)[:80]}"
        existing = issue_exists(card_id)
        if existing:
            print(f"  SKIP {card_id}: exists #{existing}")
            skipped.append((card_id, existing))
            continue

        labels = build_labels(fm, card_id)
        body = build_body(md, fm, card_id)

        # gh issue create
        cmd = ["issue", "create", "-R", REPO, "--title", title, "--body", body]
        for lb in labels[:20]:  # GitHub label cap ~20 safe
            cmd += ["--label", lb]
        r = gh(*cmd, check=False)
        if r.returncode != 0:
            print(f"  ERR {card_id}: {r.stderr[:300]}")
            errs.append((card_id, r.stderr[:400]))
            continue
        # gh issue create 输出里找 issue URL，提取 number
        out = (r.stdout or "").strip()
        m = re.search(r"/issues/(\d+)", out)
        n = m.group(1) if m else "?"
        print(f"  + {card_id} → #{n}  status={status} tier={tier} labels={len(labels)}")
        created.append((card_id, n))
        time.sleep(0.4)  # 速率友好

    print(f"\n=== SUMMARY ===")
    print(f"  created {len(created)}: {created[:5]}{'...' if len(created)>5 else ''}")
    print(f"  skipped {len(skipped)} (already existed)")
    print(f"  errors  {len(errs)} : {errs}")
    sys.exit(0 if not errs else 2)


if __name__ == "__main__":
    main()
