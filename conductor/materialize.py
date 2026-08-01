#!/usr/bin/env python3
"""conductor/materialize.py — 手册 6.2 物化校验 + 造卡（W4-3 全量实现）。

物化前四校验（任一不满足 → 不物化，开 Incident）：
1. charter 映射：每张卡有 charter 字段（CHARTER.md 缺失时用 ["G0"] 占位）
2. paths 两两不交叉
3. tier 合法（trivial / standard / critical）
4. acceptance ≥ 1 条

物化产物（全套 issue）：
- Milestone（以波次 ID 命名）
- Parent issue（type=Wave，关联 milestone）
- Sub-issues（每张卡一个 Card issue，关联 milestone + parent）
- Dependencies（blocked_by 链 → 在 card JSON 中设置并在 issue body 标注）

单向阀门：materializer 是唯一批量造 Card 的入口（由 workflow 触发保证）。
脚本自身也校验：若已有同 wave 的 Card issue 存在则跳过（幂等）。
每个创建 issue 的函数入口处用 _enforce_role(role, create_type) 强制 ROLE_CREATE_MAP。
"""
import json, os, subprocess, sys, pathlib, fnmatch, re, hashlib, datetime

E = os.environ
_repo_env = E.get("LOOP_REPO", "loop")
# Handle both short name ("loop") and full name ("Cloudbird-Software/loop")
REPO = _repo_env if "/" in _repo_env else f'{E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER",""))}/{_repo_env}'
VALID_TIERS = {"trivial", "standard", "critical"}
CRITICAL_PATTERNS = ["auth", "billing", "migrations", "deploy", ".github", "settings", "contracts"]

# 单向阀门：角色→允许创建的 issue type
ROLE_CREATE_MAP = {
    "materializer": {"Card", "Wave", "Milestone", "Incident"},  # materializer 报告自身物化失败为 Incident
    "auditor":      {"Finding"},
    "planner":      {"Wave"},  # planner 只能提波次 PR，不直接造 Card
    "impl":         set(),     # impl 不能造 Card
    "verify":       set(),     # verify 不能造 Card
    "incident":     {"Incident", "Card"},  # Incident 检测器每日最多 2 张 hotfix Card
    # R12-3: 强模型验收环角色阀门
    "reviewer":     {"Claim"},               # reviewer 只能创建 Claim 对象，不能创建 Card/Wave/Milestone/Incident
    "reproducer":   {"Reproduction", "Finding"},  # reproducer 只能创建 Reproduction 记录与对已确认 claim 的 Finding
}
INCIDENT_HOTFIX_DAILY_LIMIT = 2


def check_self_adjudication(reviewer_model, reviewer_session, reproducer_model, reproducer_session):
    """R12-3: 同一 (model, session_id) 既是 claim 作者又是 reproducer 时直接拒绝。

    异构强制（CHARTER N6）：任何角色都不得对自己产出的对象做下一步判定。
    model 维度相同即判定为自证（session 不同也不行——同一模型的两次推理不构成独立验证）。
    """
    if reviewer_model == reproducer_model:
        raise ValueError(
            f"SELF_ADJUDICATION_REFUSED: reproducer_model({reproducer_model}) "
            f"== reviewer_model({reviewer_model}) — 同一模型不得复现自己的 claim "
            f"(reviewer_session={reviewer_session}, reproducer_session={reproducer_session})"
        )


def _enforce_role(role, create_type):
    """单向阀门：校验 role 是否被允许创建 create_type 类型的 issue。

    ROLE_CREATE_MAP 定义角色→可创建类型映射；不匹配则抛 ValueError 说明越权。
    auditor 只能建 Finding；planner 只能建 Wave；impl/verify 不能建 Card；
    Incident 检测器每日最多 INCIDENT_HOTFIX_DAILY_LIMIT 张 hotfix Card；只有
    materializer 能批量造 Card。
    """
    if role is None:
        raise ValueError(
            f"ROLE_VALVE_VIOLATION: role is required to create {create_type} "
            f"(caller passed no role)"
        )
    allowed_types = ROLE_CREATE_MAP.get(role, set())
    if create_type not in allowed_types:
        raise ValueError(
            f"ROLE_VALVE_VIOLATION: role '{role}' is not allowed to create {create_type} "
            f"(allowed types for this role: {sorted(allowed_types) if allowed_types else 'none'})"
        )


def _count_today_hotfix_cards():
    """查当日已创建的 hotfix Card 数量（用于 Incident 检测器每日限额）。"""
    today = datetime.date.today().isoformat()
    p = gh("issue", "list", "-R", REPO,
           "--label", "hotfix", "--state", "all",
           "--json", "number",
           "--search", f"created:>={today}")
    try:
        return len(json.loads(p.stdout or "[]"))
    except Exception:
        return 0


def gh(*a):
    """Run gh CLI, return CompletedProcess."""
    return subprocess.run(["gh", *a], capture_output=True, text=True)


def set_milestone(issue_num, milestone_num):
    """Set milestone on an issue via API (gh issue create --milestone is unreliable)."""
    if not milestone_num:
        return
    gh("api","--method","PATCH",f"/repos/{REPO}/issues/{issue_num}",
       "-f",f"milestone={milestone_num}")


def GLOB(a, b):
    """Check if any path in a matches any path in b (glob overlap).
    Handles parent-directory relationships: src/a/** conflicts with src/a/b/**.
    """
    def _conflict(x, y):
        xs = x.rstrip("/*")
        ys = y.rstrip("/*")
        # Direct glob match
        if fnmatch.fnmatch(xs, ys) or fnmatch.fnmatch(ys, xs):
            return True
        # Parent-directory check: src/a is parent of src/a/b
        if xs == ys or xs.startswith(ys + "/") or ys.startswith(xs + "/"):
            return True
        return False
    return any(_conflict(x, y) for x in a for y in b)


# ============================================================
# Wave file parsing
# ============================================================

def extract_wave_meta(text):
    """Extract wave ID, title, summary from wave markdown."""
    wave_id = ""
    title = ""
    summary = ""
    for line in text.splitlines():
        if line.startswith("# ") and not title:
            title = line.lstrip("# ").strip()
            m = re.search(r'WAVE[-_]?\d+', title, re.IGNORECASE)
            if m:
                wave_id = m.group(0).upper().replace("_", "-")
        if line.startswith("> ") and not summary:
            summary = line.lstrip("> ").strip()
    # fallback: derive wave_id from title
    if not wave_id:
        m = re.search(r'WAVE[-_]?\d+', title + " " + summary, re.IGNORECASE)
        if m:
            wave_id = m.group(0).upper().replace("_", "-")
    return wave_id, title, summary


def extract_cards(waves_dir):
    """从 waves/ 目录的 .md 文件中提取卡片定义。"""
    cards = []
    wdir = pathlib.Path(waves_dir)
    if not wdir.exists():
        print(f"Waves dir not found: {waves_dir}")
        return cards, []
    wave_metas = []
    for f in sorted(wdir.glob("**/*.md")):
        text = f.read_text()
        wave_id, wave_title, wave_summary = extract_wave_meta(text)
        wave_metas.append({"file": str(f), "id": wave_id, "title": wave_title, "summary": wave_summary})
        # 提取 ```json loop 代码块
        for m in re.finditer(r'```json loop\n(.*?)```', text, re.DOTALL):
            try:
                card = json.loads(m.group(1).strip())
                card["_source"] = str(f)
                if wave_id and not card.get("wave"):
                    card["wave"] = wave_id
                cards.append(card)
            except json.JSONDecodeError as e:
                print(f"BAD JSON in {f}: {e}")
    return cards, wave_metas


# ============================================================
# Charter mapping check
# ============================================================

def load_charter_ids():
    """Load valid charter IDs from CHARTER.md if it exists."""
    charter_path = pathlib.Path("CHARTER.md")
    if not charter_path.exists():
        # Also check product-x workspace
        ws = E.get("LOOP_WS", "/work/product-x")
        charter_path = pathlib.Path(ws) / "CHARTER.md"
    if not charter_path.exists():
        return None  # CHARTER.md missing
    text = charter_path.read_text()
    ids = set()
    for m in re.finditer(r'^([GNUQ]\d+)\s', text, re.MULTILINE):
        ids.add(m.group(1))
    return ids if ids else None


def validate_charter(card, charter_ids, cid):
    """Validate charter mapping for a card."""
    charter = card.get("charter")
    if not charter:
        return f"Card {cid}: missing charter mapping"
    if charter_ids is None:
        # CHARTER.md missing → accept ["G0"] placeholder
        if charter != ["G0"]:
            # Auto-fix to placeholder
            card["charter"] = ["G0"]
            print(f"  ⚠ {cid}: CHARTER.md missing, charter set to ['G0'] placeholder")
        return None
    for ref in charter:
        if ref not in charter_ids:
            return f"Card {cid}: charter ref '{ref}' not found in CHARTER.md"
    return None


# ============================================================
# Four validations
# ============================================================

def _build_dependency_pairs(cards):
    """Build set of (blocked_id, blocker_id) pairs from blocked_by fields.
    If A is blocked_by [B], then (A_id, B_id) means B must complete before A.
    Transitively resolved: if A blocked_by B and B blocked_by C, then A also blocked_by C.
    These pairs are exempt from path conflict detection because they guarantee sequential execution.
    """
    blockers = {}
    for c in cards:
        cid = c.get("id", "")
        bby = c.get("blocked_by", []) or []
        if cid and bby:
            blockers[cid] = set(bby)
    # Transitive closure
    changed = True
    while changed:
        changed = False
        for cid, deps in list(blockers.items()):
            for dep in list(deps):
                if dep in blockers:
                    new_deps = blockers[dep] - deps
                    if new_deps:
                        deps.update(new_deps)
                        changed = True
    # Return set of (blocked_id, blocker_id) pairs
    pairs = set()
    for cid, deps in blockers.items():
        for dep in deps:
            pairs.add((cid, dep))
    return pairs


def validate(cards, charter_ids):
    """校验四项，返回 (errors, valid_cards)。
    blocked_by 机制作为路径冲突豁免：若卡 A blocked_by 卡 B，则 A/B 交叉可接受
    （B 完成前 A 不会启动，串行执行不会产生冲突）。
    """
    errors = []
    valid = []
    for i, card in enumerate(cards):
        cid = card.get("id", f"unnamed-{i}")
        card_errors = []
        # 1. charter 映射
        err = validate_charter(card, charter_ids, cid)
        if err:
            card_errors.append(err)
        # 2. paths 非空
        if not card.get("paths"):
            card_errors.append(f"Card {cid}: missing paths")
        # 3. tier 合法
        tier = card.get("tier", "standard")
        if tier not in VALID_TIERS:
            card_errors.append(f"Card {cid}: invalid tier '{tier}' (must be one of {VALID_TIERS})")
        # 4. acceptance >= 1
        if not card.get("acceptance") or len(card.get("acceptance", [])) < 1:
            card_errors.append(f"Card {cid}: acceptance must have >= 1 criterion")
        if card_errors:
            errors.extend(card_errors)
        else:
            valid.append(card)
    # 5. paths 两两不交叉（只在 valid 卡之间检测；blocked_by 机制豁免）
    dep_pairs = _build_dependency_pairs(valid)
    for i, a in enumerate(valid):
        for b in valid[i+1:]:
            aid = a.get("id", "?")
            bid = b.get("id", "?")
            if GLOB(a.get("paths",[]), b.get("paths",[])):
                # Check if this conflict is exempted by blocked_by
                exempt = (aid, bid) in dep_pairs or (bid, aid) in dep_pairs
                if exempt:
                    errors.append(f"Path conflict (EXEMPTED by blocked_by): {aid} and {bid}")
                else:
                    errors.append(f"Path conflict: {aid} and {bid}")
    # Re-filter: remove ONLY cards that have non-exempted path conflicts
    conflict_ids = set()
    for e in errors:
        if "EXEMPTED" in e:
            continue
        m = re.match(r"Path conflict: (\S+) and (\S+)", e)
        if m:
            conflict_ids.add(m.group(1))
            conflict_ids.add(m.group(2))
    if conflict_ids:
        valid = [c for c in valid if c.get("id") not in conflict_ids]
    return errors, valid


# ============================================================
# Tier auto-judge
# ============================================================

def auto_tier(card):
    """Auto-promote tier to critical if paths hit sensitive patterns."""
    paths = card.get("paths", [])
    if any(any(patt in p for patt in CRITICAL_PATTERNS) for p in paths):
        if card.get("tier") != "critical":
            old = card.get("tier", "standard")
            card["tier"] = "critical"
            print(f"  → {card.get('id','?')}: tier {old} → critical (path match)")


# ============================================================
# Idempotency check
# ============================================================

def check_already_materialized(wave_id):
    """Check if cards for this wave already exist (idempotency)."""
    if not wave_id:
        return False
    p = gh("issue","list","-R",REPO,"--state","all","--limit","200",
           "--json","number,title,body","--search",f"in:body {wave_id}")
    try:
        issues = json.loads(p.stdout or "[]")
        for it in issues:
            blk = extract_block(it.get("body",""))
            if blk and blk.get("wave") == wave_id and blk.get("schema") == 1:
                return True
    except Exception:
        pass
    return False


def extract_block(body):
    """Extract ```json loop block from issue body."""
    m = "```json loop"
    if m not in (body or ""):
        return None
    seg = body.split(m, 1)[1].split("```", 1)[0]
    try:
        return json.loads(seg)
    except Exception:
        return None


# ============================================================
# Milestone creation
# ============================================================

def create_milestone(wave_id, title, role):
    """Create a GitHub milestone for the wave."""
    _enforce_role(role, "Milestone")
    p = gh("api","--method","POST",f"/repos/{REPO}/milestones",
           "-f",f"title={wave_id} — {title}",
           "-f","state=open",
           "-f",f"description=Milestone for wave {wave_id}")
    if p.returncode == 201:
        ms = json.loads(p.stdout)
        print(f"  → milestone created: #{ms['number']} ({wave_id})")
        return ms["number"]
    # Maybe already exists
    p2 = gh("api",f"/repos/{REPO}/milestones")
    try:
        for ms in json.loads(p2.stdout or "[]"):
            if wave_id in ms.get("title",""):
                print(f"  → milestone exists: #{ms['number']} ({wave_id})")
                return ms["number"]
    except Exception:
        pass
    print(f"  ⚠ milestone creation failed: {p.stderr}")
    return None


# ============================================================
# Parent Wave issue
# ============================================================

def create_parent_issue(wave_id, title, summary, milestone_num, card_count, role):
    """Create parent Wave issue that tracks all sub-issues."""
    _enforce_role(role, "Wave")
    body = f"""# Wave: {wave_id}

{summary}

## Stats
- Cards: {card_count}
- Milestone: #{milestone_num}

## Card Checklist
"""
    # Placeholder — will be updated after sub-issues are created
    args = ["issue","create","-R",REPO,
           "--title",f"[Wave] {wave_id} — {title}",
           "--label","wave",
           "--body",body]
    p = gh(*args)
    if p.returncode == 0:
        num = int(p.stdout.strip().split("/")[-1])
        set_milestone(num, milestone_num)
        print(f"  → parent Wave issue: #{num}")
        return num
    print(f"  ⚠ parent issue creation failed: {p.stderr}")
    return None


def update_parent_issue(parent_num, cards, card_issues):
    """Update parent issue with sub-issue checklist."""
    body = f"""# Wave: {cards[0].get('wave','')}

## Card Checklist
"""
    for card, issue_num in card_issues:
        cid = card.get("id","?")
        obj = card.get("objective","?")
        tier = card.get("tier","standard")
        dep = f" (blocked_by: {card['blocked_by']})" if card.get("blocked_by") else ""
        body += f"- [ ] #{issue_num} — {cid} (O:{obj}, tier:{tier}){dep}\n"
    body += f"\n## Total: {len(card_issues)} cards\n"
    # Write back
    import tempfile
    f = pathlib.Path(tempfile.gettempdir()) / f"parent-{parent_num}.tmp"
    f.write_text(body)
    gh("issue","edit",str(parent_num),"-R",REPO,"--body-file",str(f))


# ============================================================
# Card issue creation (batch — only materializer does this)
# ============================================================

def create_card_issue(card, milestone_num, parent_num, role):
    """Create a Card issue with full JSON block and metadata."""
    # 单向阀门：只有 materializer（批量造卡）或 incident（hotfix 卡）可造 Card
    _enforce_role(role, "Card")
    # Auto-tier
    auto_tier(card)
    # Ensure state is ready for dispatch
    card["state"] = "ready"
    card.setdefault("claim_id", None)
    card.setdefault("lease_until", None)
    card.setdefault("heartbeat_at", None)
    card.setdefault("attempt", 0)
    card.setdefault("session_ordinal", None)
    card.setdefault("model", None)

    # Build issue body
    obj = card.get("objective","?")
    tier = card.get("tier","standard")
    paths = card.get("paths",[])
    forbid = card.get("forbid_paths",[])
    charter = card.get("charter",[])
    acceptance = card.get("acceptance",[])
    blocked_by = card.get("blocked_by")
    deps_str = f" (blocked_by: {blocked_by})" if blocked_by else ""

    body = f"""```json loop
{json.dumps(card, indent=2, ensure_ascii=False)}
```

**Wave:** {card.get('wave','?')}  **Objective:** {obj}  **Tier:** {tier}{deps_str}
**Charter:** {', '.join(charter)}
**Paths:** {', '.join(paths)}
**Forbid:** {', '.join(forbid)}

## Acceptance Criteria
"""
    for i, ac in enumerate(acceptance, 1):
        body += f"{i}. {ac}\n"
    if blocked_by:
        body += f"\n⚠ Blocked by card(s): {blocked_by}\n"

    args = ["issue","create","-R",REPO,
            "--title",f"[Card] {card.get('id','unnamed')} — {obj}",
            "--label","card",
            "--body",body]

    p = gh(*args)
    if p.returncode == 0:
        num = int(p.stdout.strip().split("/")[-1])
        set_milestone(num, milestone_num)
        print(f"  → Card #{num}: {card.get('id','?')} (O:{obj}, tier:{tier})")
        return num
    print(f"  ⚠ Card creation failed for {card.get('id','?')}: {p.stderr}")
    return None


# ============================================================
# Incident
# ============================================================

def open_incident(title, body, role):
    """校验失败时开 Incident。

    单向阀门：role 必须有权创建 Incident。Incident 检测器（role='incident'）
    每日最多 INCIDENT_HOTFIX_DAILY_LIMIT 张 hotfix Card，超限则拒绝并打印
    INCIDENT_HOTFIX_LIMIT_EXCEEDED。
    """
    _enforce_role(role, "Incident")
    # 每日 hotfix 限额：仅 Incident 检测器（role='incident'）受此约束
    if role == "incident":
        count = _count_today_hotfix_cards()
        if count >= INCIDENT_HOTFIX_DAILY_LIMIT:
            print(f"INCIDENT_HOTFIX_LIMIT_EXCEEDED: {count} hotfix card(s) "
                  f"already created today (limit={INCIDENT_HOTFIX_DAILY_LIMIT})")
            return None
    full_body = "## Materialization Failed\n\n" + body
    p = gh("issue","create","-R",REPO,
           "--title",title,
           "--label","incident",
           "--body",full_body)
    if p.returncode == 0:
        num = p.stdout.strip().split("/")[-1]
        print(f"  → opened Incident #{num}: {title}")
        return num
    else:
        print(f"  ⚠ Incident creation failed: {p.stderr}")
        return None


# ============================================================
# Main materialization
# ============================================================

def materialize_wave(cards, wave_meta):
    """Full materialization: milestone + parent + sub-issues + deps."""
    wave_id = wave_meta.get("id") or (cards[0].get("wave","") if cards else "")
    wave_title = wave_meta.get("title","Wave")
    wave_summary = wave_meta.get("summary","")

    if not wave_id:
        wave_id = "WAVE-UNKNOWN"

    # Idempotency check
    if check_already_materialized(wave_id):
        print(f"SKIP: Wave {wave_id} already materialized (idempotency).")
        return False

    # 1. Create milestone
    print(f"[1/4] Creating milestone for {wave_id}...")
    milestone_num = create_milestone(wave_id, wave_title, role="materializer")

    # 2. Create parent Wave issue
    print(f"[2/4] Creating parent Wave issue...")
    parent_num = create_parent_issue(wave_id, wave_title, wave_summary, milestone_num, len(cards), role="materializer")

    # 3. Create Card issues (batch — valve: only materializer does this)
    print(f"[3/4] Materializing {len(cards)} card(s)...")
    card_issues = []
    card_id_to_issue = {}
    for card in cards:
        num = create_card_issue(card, milestone_num, parent_num, role="materializer")
        if num:
            card_issues.append((card, num))
            card_id_to_issue[card.get("id")] = num

    # 4. Set up dependencies (blocked_by cross-references)
    print(f"[4/4] Setting up dependencies...")
    for card, num in card_issues:
        blocked_by = card.get("blocked_by")
        if blocked_by:
            if isinstance(blocked_by, str):
                blocked_by = [blocked_by]
            dep_issues = [str(card_id_to_issue.get(b, b)) for b in blocked_by]
            dep_str = ", ".join(f"#{d}" for d in dep_issues)
            gh("issue","comment",str(num),"-R",REPO,
               "--body",f"⚠ Blocked by: {dep_str}. Will become ready when all deps are merged.")
            print(f"  → #{num} blocked_by {dep_str}")

    # Update parent issue with checklist
    if parent_num:
        update_parent_issue(parent_num, cards, card_issues)

    print(f"\n=== Materialization complete: {len(card_issues)} cards, milestone #{milestone_num}, parent #{parent_num} ===")
    # Anti-fake-green: if any card failed to create, return False so main() can exit 1
    return len(card_issues) == len(cards)


def main():
    waves_dir = sys.argv[1] if len(sys.argv) > 1 else "waves/"
    print(f"=== materializer: scanning {waves_dir} ===")

    cards, wave_metas = extract_cards(waves_dir)
    print(f"Found {len(cards)} card(s) in {len(wave_metas)} wave file(s)")

    if not cards:
        print("No cards to materialize.")
        return

    # Load charter IDs (may be None if CHARTER.md missing)
    charter_ids = load_charter_ids()
    if charter_ids is None:
        print("⚠ CHARTER.md not found — using ['G0'] placeholder for charter mapping")
        # Record in DECISIONS.md
        decisions = pathlib.Path("DECISIONS.md")
        if decisions.exists():
            text = decisions.read_text()
            todo_entry = f"\n## ADR-PENDING: CHARTER.md missing — charter mapping using placeholder\n\n**日期:** auto\n**状态:** 待办\n\nCHARTER.md not found during materialization. All cards use charter: [\"G0\"] placeholder.\nNeed to write CHARTER.md and re-map charter fields.\n"
            if "CHARTER.md missing" not in text:
                decisions.write_text(text + todo_entry)
                print("  → recorded TODO in DECISIONS.md")

    # Validate
    errors, valid = validate(cards, charter_ids)
    if errors:
        print(f"\nVALIDATION FAILED: {len(errors)} error(s)")
        for e in errors:
            print(f"  ✗ {e}")
        error_body = "\n".join(f"- {e}" for e in errors)
        open_incident(
            f"Materializer: validation failed for wave",
            error_body,
            role="materializer"
        )
        sys.exit(1)

    print(f"\nAll {len(valid)} card(s) passed validation.")
    for c in valid:
        print(f"  ✓ {c.get('id','?')} (tier:{c.get('tier','standard')}, O:{c.get('objective','?')})")

    # Materialize each wave
    failures = 0
    for wave_meta in wave_metas:
        wave_cards = [c for c in valid if c.get("wave") == wave_meta.get("id")]
        if not wave_cards:
            # Try matching by source file
            wave_cards = [c for c in valid if c.get("_source") == wave_meta.get("file")]
        if wave_cards:
            ok = materialize_wave(wave_cards, wave_meta)
            if not ok:
                failures += 1

    if failures:
        print(f"\nERROR: {failures} wave(s) had materialization failures — see ⚠ messages above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
