#!/usr/bin/env python3
"""conductor/materialize.py — 手册 6.2 物化校验 + 造卡。

校验四项（任一不满足 → 不物化，开 Incident）：
1. charter 映射：每张卡有 charter 字段
2. paths 两两不交叉
3. tier 合法（trivial / standard / critical）
4. acceptance ≥ 1 条
"""
import json, os, subprocess, sys, pathlib, fnmatch, re

E = os.environ
REPO = f'{E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER",""))}/{E.get("LOOP_REPO","product-x")}'
VALID_TIERS = {"trivial", "standard", "critical"}

def gh(*a):
    return subprocess.run(["gh", *a], capture_output=True, text=True)

def GLOB(a, b):
    return any(fnmatch.fnmatch(x.rstrip("/*"), y.rstrip("/*")) or
               fnmatch.fnmatch(y.rstrip("/*"), x.rstrip("/*")) for x in a for y in b)

def extract_cards(waves_dir):
    """从 waves/ 目录的 .md 文件中提取卡片定义。"""
    cards = []
    wdir = pathlib.Path(waves_dir)
    if not wdir.exists():
        print(f"Waves dir not found: {waves_dir}")
        return cards
    for f in sorted(wdir.glob("**/*.md")):
        text = f.read_text()
        # 提取 ```json loop 代码块
        for m in re.finditer(r'```json loop\n(.*?)```', text, re.DOTALL):
            try:
                card = json.loads(m.group(1).strip())
                card["_source"] = str(f)
                cards.append(card)
            except json.JSONDecodeError as e:
                print(f"BAD JSON in {f}: {e}")
    return cards

def validate(cards):
    """校验四项，返回 (errors, valid_cards)。"""
    errors = []
    valid = []
    for i, card in enumerate(cards):
        cid = card.get("id", f"unnamed-{i}")
        # 1. charter 映射
        if not card.get("charter"):
            errors.append(f"Card {cid}: missing charter mapping")
        # 2. paths 非空
        if not card.get("paths"):
            errors.append(f"Card {cid}: missing paths")
        # 3. tier 合法
        tier = card.get("tier", "standard")
        if tier not in VALID_TIERS:
            errors.append(f"Card {cid}: invalid tier '{tier}' (must be one of {VALID_TIERS})")
        # 4. acceptance >= 1
        if not card.get("acceptance") or len(card.get("acceptance", [])) < 1:
            errors.append(f"Card {cid}: acceptance must have >= 1 criterion")
        if not any(e.startswith(f"Card {cid}:") for e in errors):
            valid.append(card)
    # 5. paths 两两不交叉
    for i, a in enumerate(valid):
        for b in valid[i+1:]:
            if GLOB(a.get("paths",[]), b.get("paths",[])):
                errors.append(f"Path conflict: {a.get('id','?')} and {b.get('id','?')}")
    return errors, valid

def materialize(cards):
    """为每张有效卡创建 Card issue。"""
    for card in cards:
        body = f"""```json loop
{json.dumps(card, indent=2, ensure_ascii=False)}
```

**Charter:** {card.get('charter','')}
**Tier:** {card.get('tier','standard')}
**Paths:** {', '.join(card.get('paths',[]))}

## Acceptance Criteria
"""
        for i, ac in enumerate(card.get("acceptance", []), 1):
            body += f"{i}. {ac}\n"
        p = gh("issue","create","-R",REPO,
               "--title",f"[Card] {card.get('id','unnamed')}",
               "--label","card","--body",body)
        print(f"  → materialized: {card.get('id','?')} -> {p.stdout.strip()}")

def open_incident(errors):
    """校验失败时开 Incident。"""
    body = "## Materialization Failed\n\nErrors:\n\n" + "\n".join(f"- {e}" for e in errors)
    gh("issue","create","-R",REPO,
       "--title","Materializer: validation failed",
       "--label","incident","--body",body)
    print(f"  → opened Incident with {len(errors)} errors")

def main():
    waves_dir = sys.argv[1] if len(sys.argv) > 1 else "waves/"
    print(f"=== materializer: scanning {waves_dir} ===")
    cards = extract_cards(waves_dir)
    print(f"Found {len(cards)} card(s)")
    if not cards:
        print("No cards to materialize.")
        return
    errors, valid = validate(cards)
    if errors:
        print(f"VALIDATION FAILED: {len(errors)} error(s)")
        for e in errors:
            print(f"  ✗ {e}")
        open_incident(errors)
        sys.exit(1)
    print(f"All {len(valid)} card(s) passed validation.")
    materialize(valid)
    print("=== materialization complete ===")

if __name__ == "__main__":
    main()
