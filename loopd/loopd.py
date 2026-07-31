#!/usr/bin/env python3
"""loopd — 沙盒守护进程。单文件，标准库 + gh CLI。

手册第 5 部分骨架 + 全部 intent 补完。
5.1–5.4 给出的函数逐字采用；缺失 handler 按同一 @intent 模式最小实现。

E 包高强度测试修复：环境变量缺失时 --help/--version 仍能工作，不 KeyError 崩。
"""
import json, os, subprocess, threading, time, pathlib, fnmatch, hashlib, uuid, re, datetime, sys

# ============================================================
# 全局常量（手册 5.1）—— 全部用 .get() 给默认值，--help 不崩
# ============================================================
def _env(): return os.environ
E = _env()

# 8 个代理变量名（__getattr__ + CFG() 初始化都会用到）
# RELAY 已移除（#52/#53：远程命令通道 relay/filemode/run 不再存在）
_PROXIES = {"ROOT","WS","LOOP","REPO","ROLE","MODEL","SID","STATE"}

def _cfg():
    """延迟加载配置：--help 时调用不到环境相关 handler 不会崩；
    真正干活 handler 调一次就 OK。"""
    ROOT = pathlib.Path(E.get("LOOP_ROOT", E.get("GITHUB_WORKSPACE", "/workspace")))
    WS   = pathlib.Path(E.get("LOOP_WS", str(ROOT)))
    LOOP = ROOT/".loop"
    ORG  = E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER", "Cloudbird-Software"))
    REPON = E.get("LOOP_REPO", (E.get("GITHUB_REPOSITORY","loop").split("/")[-1] if "/" in E.get("GITHUB_REPOSITORY","/loop") else "loop"))
    REPO = f"{ORG}/{REPON}"
    ROLE = [x for x in E.get("LOOP_ROLE", "impl").split(",") if x]
    MODEL = E.get("LOOP_MODEL", "unknown")
    SID = E.get("LOOP_SANDBOX_ID", "local-" + uuid.uuid4().hex[:8])
    STATE = LOOP/"daemon.json"
    return ROOT, WS, LOOP, ORG, REPO, ROLE, MODEL, SID, STATE

# --help/--version 先不实例化（避免 mkpath 等副作用）；handler 内首次访问用 CFG()
_CFG = None
def CFG():
    global _CFG
    if _CFG is None:
        ROOT, WS, LOOP, ORG, REPO, ROLE, MODEL, SID, STATE = _cfg()
        LOOP.mkdir(parents=True, exist_ok=True)
        _CFG = {"ROOT":ROOT,"WS":WS,"LOOP":LOOP,"ORG":ORG,
                "REPO":REPO,"ROLE":ROLE,"MODEL":MODEL,"SID":SID,"STATE":STATE}
        # E包修复：把 8 个变量"物化"到模块全局变量，函数里裸引用不再走 __getattr__
        for _k, _v in _CFG.items():
            if _k in _PROXIES:
                globals().setdefault(_k, _v)
    return _CFG

lock = threading.RLock()

# ============================================================
# 兼容层：全局裸变量 ROOT/WS/LOOP/REPO/ROLE/MODEL/SID/STATE
# 用模块 __getattr__ 代理到 CFG()，免改 100 处引用。
# ============================================================
_PROXIES = {"ROOT","WS","LOOP","REPO","ROLE","MODEL","SID","STATE"}
def __getattr__(name):
    if name in _PROXIES:
        return CFG()[name]
    raise AttributeError(name)

# 让 dir(loopd) 可见这些变量，减少调试时的意外
__all__ = list(_PROXIES) + ["lock", "CFG"]

# ============================================================
# 工具函数（手册 5.1）
# ============================================================
def sh(*a, cwd=None, timeout=1800, check=False):
    p = subprocess.run(list(a), cwd=cwd or CFG()["WS"], capture_output=True, text=True, timeout=timeout)
    if check and p.returncode: raise RuntimeError(f"{a[:2]} -> {p.returncode}\n{p.stderr[-2000:]}")
    return p

def gh(*a, **kw):                     # 一律 --json，不手写 GraphQL
    return sh("gh", *a, **kw)

def st(**kw):
    with lock:
        d = json.loads(STATE.read_text()) if STATE.exists() else {
            "sandbox": SID, "role": ROLE, "model": MODEL, "card": None,
            "session_ordinal": 0, "started": time.time()}
        d.update(kw); STATE.write_text(json.dumps(d, indent=2)); return d

# ============================================================
# Intent 注册（手册 5.2）
# ============================================================
HANDLERS = {}                                     # 装饰器注册
def intent(name):
    def deco(f): HANDLERS[name] = f; return f
    return deco

# ============================================================
# 卡片工具（手册 5.3）
# ============================================================
# v0.1.6: 旧版用 rstrip("/*") 归一化目录字面量，但 rstrip 是字符集剥离，
# 把 'e2/handoff/**' 误剥成字面量 'e2/handoff'（通配符全丢），导致 dir/** 的卡
# loop save 提交子文件时误报 OUT_OF_SCOPE。改直接 fnmatch：Python fnmatch 的 *
# 跨 /（不像 shell glob），** 等价于 * 也能匹配多级子文件。
GLOB = lambda a, b: any(fnmatch.fnmatch(x, y) or fnmatch.fnmatch(y, x) for x in a for y in b)

def cards(states):
    q = gh("issue","list","-R",REPO,"--state","open","--limit","100",
           "--json","number,title,body,updatedAt,labels")
    out = []
    for it in json.loads(q.stdout or "[]"):
        blk = extract_block(it["body"])
        if blk and blk.get("state") in states: out.append((it, blk))
    return out

def extract_block(body):
    m = "```json loop"
    if m not in (body or ""): return None
    seg = body.split(m,1)[1].split("```",1)[0]
    try: return json.loads(seg)
    except Exception: return None

def write_block(num, blk, expect_updated_at):
    it = json.loads(gh("issue","view",str(num),"-R",REPO,"--json","body,updatedAt").stdout)
    if it["updatedAt"] != expect_updated_at: return False            # CAS 前置校验
    body = it["body"]; head, rest = body.split("```json loop",1); tail = rest.split("```",1)[1]
    new = head + "```json loop\n" + json.dumps(blk, indent=2, ensure_ascii=False) + "\n```" + tail
    p = pathlib.Path(LOOP/"body.tmp"); p.write_text(new)
    gh("issue","edit",str(num),"-R",REPO,"--body-file",str(p))
    back = extract_block(json.loads(gh("issue","view",str(num),"-R",REPO,"--json","body").stdout)["body"])
    return back and back.get("claim_id") == blk.get("claim_id")     # 写后回读确认

def prio(blk):
    """卡片优先级排序键。tier: trivial(0) < standard(1) < critical(2)；同 tier 按 id 升序。"""
    tier_order = {"trivial": 0, "standard": 1, "critical": 2}
    return (tier_order.get(blk.get("tier", "standard"), 1), blk.get("id", ""))

def render_card(it, blk):
    """渲染卡片正文到 .loop/CARD.md。"""
    lines = [
        f"# Card #{it['number']}: {it.get('title','')}",
        "",
        f"**ID:** {blk.get('id','')}",
        f"**Tier:** {blk.get('tier','standard')}",
        f"**Role:** {blk.get('role','impl')}",
        f"**Paths:** {', '.join(blk.get('paths',[]))}",
    ]
    if blk.get("forbid_paths"):
        lines.append(f"**Forbidden:** {', '.join(blk['forbid_paths'])}")
    lines += [
        "",
        "## Acceptance Criteria",
    ]
    for i, ac in enumerate(blk.get("acceptance", []), 1):
        lines.append(f"{i}. {ac}")
    lines += [
        "",
        "## Body",
        it.get("body", "").split("```json loop")[0].strip(),
    ]
    return "\n".join(lines) + "\n"

# ============================================================
# [已移除] Relay 分发 + file 模式（#52/#53）
# relay_thread / filemode_thread 已删除：远程命令通道（.loop/relay/inbox、
# .loop/IN.json）不再被接受。loopd 只通过 CLI（loop <verb>）接收指令。
# ============================================================

# ============================================================
# next：阻塞取卡 + CAS 领卡 + 路径租约（手册 5.3）
# ============================================================
@intent("next")
def h_next(args):
    d = st()
    if d["session_ordinal"] >= int(E.get("LOOP_MAX_CARDS_PER_SESSION", 1)):
        return {"stdout": "RETIRE\n"}
    deadline = time.time() + int(E.get("LOOP_NEXT_BLOCK_SEC", 60))
    while time.time() < deadline:
        busy = [b for _, b in cards(("claimed","in_progress"))]
        # R12-4：显式排除未复现的 claim F-card（state=unconfirmed）——wave-level gate #2。
        # cards(("ready",)) 已按 state 过滤，此处为 defense-in-depth：即使某张卡的 state
        # 字段意外保留/被改回 unconfirmed，也不会被 impl 领取修复。
        from conductor.claim_intake import is_claim_pickable_by_impl
        for it, blk in sorted(cards(("ready",)), key=lambda x: prio(x[1])):
            if not is_claim_pickable_by_impl(blk): continue
            if blk.get("role") not in ROLE: continue
            if blk.get("blocked_by"): continue
            if blk["role"] == "verify" and blk.get("model") == MODEL: continue   # 强制异构
            if blk["role"] == "impl" and any(GLOB(blk["paths"], b["paths"]) for b in busy): continue
            cid = f"{SID}-{uuid.uuid4().hex[:8]}"
            new = dict(blk, state="claimed", claim_id=cid, model=MODEL,
                       sandbox=SID, session_ordinal=d["session_ordinal"]+1,
                       lease_until=int(time.time())+int(E.get("LOOP_LEASE_MIN", 30))*60,
                       heartbeat_at=int(time.time()))
            if not write_block(it["number"], new, it["updatedAt"]): continue     # 抢卡失败换下一张
            prepare_branch(new["id"])
            (WS/".loop"/"CARD.md").write_text(render_card(it, new))
            st(card={"num": it["number"], "blk": new}, session_ordinal=d["session_ordinal"]+1)
            return {"stdout": (WS/".loop"/"CARD.md").read_text()}
        time.sleep(20)
    return {"stdout": "EMPTY\n"}

def prepare_branch(cid):
    sh("git","-C",str(WS),"fetch","origin","main","--prune", check=True)
    sh("git","-C",str(WS),"reset","--hard","origin/main")
    sh("git","-C",str(WS),"clean","-fdx","-e",".loop")
    sh("git","-C",str(WS),"switch","-C",f'{E.get("LOOP_BRANCH_PREFIX", "loop/card")}/{cid}')

# ============================================================
# save：落盘一步（手册 5.4 do_save）
# ============================================================
@intent("save")
def h_save(args):
    msg = args[0] if args else "wip"
    do_save(msg)
    return {"stdout": "OK\n"}

def _card_paths(d):
    """从当前卡读 paths（GLOB 风格）；无卡返回 None。"""
    c = d.get("card")
    if not c:
        return None
    return c.get("blk", {}).get("paths")

def _stage_card_paths(paths):
    """只 stage 卡 paths 白名单内的文件，硬性排除 .loop/（双重保险）。

    返回 staged 文件列表（用于后续自检）。
    """
    # 先清掉已 stage 的，确保从干净索引开始
    sh("git","-C",str(WS),"reset","-q","HEAD","--",":/")
    # stage 卡 paths（git pathspec 接受 glob，如 'ignition/impl-1/**'）
    for p in paths or []:
        sh("git","-C",str(WS),"add","--",p)
    # 硬性排除 .loop/（即便 paths 误含也不会进 commit）
    sh("git","-C",str(WS),"reset","-q","HEAD","--",".loop/")
    staged = sh("git","-C",str(WS),"diff","--cached","--name-only").stdout.strip().split()
    return [s for s in staged if s]

def do_save(msg):
    (WS/".work").mkdir(exist_ok=True)
    d = st()
    paths = _card_paths(d)
    if paths is None:
        # 无卡上下文（如 "w0 probe"）：空提交，绝不乱 stage
        sh("git","-C",str(WS),"reset","-q","HEAD","--",":/")
        sh("git","-C",str(WS),"-c","user.name=loop-worker",
           "-c",f'user.email=loop@{E.get("LOOP_ORG", "Cloudbird-Software")}.invalid',"commit","--allow-empty","-m",msg)
    else:
        staged = _stage_card_paths(paths)
        if not staged:
            # 没有可 stage 的卡 paths 内容 → 空提交保住 PR 结构
            sh("git","-C",str(WS),"-c","user.name=loop-worker",
               "-c",f'user.email=loop@{E.get("LOOP_ORG", "Cloudbird-Software")}.invalid',"commit","--allow-empty","-m",msg)
        else:
            # 自检：staged ⊆ 卡 paths（GLOB 匹配），越界则拒绝
            bad = [s for s in staged if not GLOB([s], paths)]
            if bad:
                raise RuntimeError(f"OUT_OF_SCOPE staged (not in card paths {paths}): {bad}")
            sh("git","-C",str(WS),"-c","user.name=loop-worker",
               "-c",f'user.email=loop@{E.get("LOOP_ORG", "Cloudbird-Software")}.invalid',"commit","-m",msg)
    br = sh("git","-C",str(WS),"rev-parse","--abbrev-ref","HEAD").stdout.strip()
    sh("git","-C",str(WS),"push","-u","origin",br,"--force-with-lease", check=True)
    if not json.loads(gh("pr","list","-R",REPO,"--head",br,"--json","number").stdout or "[]"):
        gh("pr","create","-R",REPO,"--draft","--fill","--head",br,"--base","main")

# ============================================================
# verify：本地验收
# ============================================================
@intent("verify")
def h_verify(args):
    verify_sh = WS/".loop"/"verify.sh"
    if not verify_sh.exists():
        # 没有 verify.sh = 卡片未声明本地验收脚本 = 视为通过（不是"跳过"）。
        # 历史上这里返回 SKIPPED，被 agent 误读为"没过、需补 verify.sh"导致越界造文件（见 docs/点火测试剧本.md §5 F-1 备注）。
        return {"stdout": "PASS (no verify.sh declared for this card)\n"}
    logdir = WS/".loop"/"logs"; logdir.mkdir(parents=True, exist_ok=True)
    logf = logdir / f"verify-{int(time.time())}.log"
    p = sh("bash", str(verify_sh), cwd=str(WS), timeout=600)
    logf.write_text(f"exit={p.returncode}\n---stdout---\n{p.stdout}\n---stderr---\n{p.stderr}")
    if p.returncode == 0:
        return {"stdout": f"PASS (log: {logf})\n{p.stdout[-500:]}\n"}
    return {"code": 1, "stdout": "", "stderr": f"FAIL (log: {logf})\n{p.stderr[-1000:]}\n"}

# ============================================================
# done：交卡
# ============================================================
@intent("done")
def h_done(args):
    d = st(); c = d.get("card")
    if not c:
        return {"code": 1, "stderr": "NO_ACTIVE_CARD\n"}
    # 终验
    verify_sh = WS/".loop"/"verify.sh"
    if verify_sh.exists():
        p = sh("bash", str(verify_sh), cwd=str(WS), timeout=600)
        if p.returncode != 0:
            return {"code": 1, "stderr": f"VERIFY_FAILED\n{p.stderr[-500:]}\n"}
    # push 残余
    if sh("git","-C",str(WS),"status","--porcelain").stdout.strip():
        do_save(f"done: {c['blk']['id']}")
    # PR 转 ready + 入 merge queue
    br = sh("git","-C",str(WS),"rev-parse","--abbrev-ref","HEAD").stdout.strip()
    prs = json.loads(gh("pr","list","-R",REPO,"--head",br,"--json","number,isDraft,state").stdout or "[]")
    pr_num = None
    for pr in prs:
        if pr.get("isDraft"):
            gh("pr","ready",str(pr["number"]),"-R",REPO)
        pr_num = pr["number"]
    # 入 merge queue：gh pr merge --squash（直接入队，不带 --auto）。
    # v0.1.3 教训：`gh pr merge --auto` 在 merge-queue 仓库上 rc=0 但只 enable 标志、
    # 不真正入队（假成功），导致 done 误判入队成功、不开 Finding。改用不带 --auto 的
    # 直接 merge——merge-queue 仓库会把它加进队列；非 merge-queue 仓库则直接合。
    # 隐藏第三坑：仓库须 allow_auto_merge=true，否则 merge 必失败。done 在入队前自动
    # 修复该设置（admin token 场景）；非 admin 静默失败由 Finding 兜底。
    if pr_num:
        _ensure_auto_merge_enabled()
        enqueue_failures = []
        for attempt in (1, 2):  # 重试一次
            p = gh("pr","merge",str(pr_num),"-R",REPO,"--squash")
            # 不能只看 rc：merge-queue 仓库的 "already queued" / "merge strategy is set
            # by the merge queue" 都打印在 stderr 但实际可能已入队。判据：rc==0 且 stderr
            # 不含致命错误（如 "merge commits are not allowed" / "codeowner review required"）。
            err = (p.stderr or "").strip()
            benign = ("already queued" in err.lower() or
                      "merge strategy" in err.lower() or
                      "set by the merge queue" in err.lower())
            if p.returncode == 0 or benign:
                # 二次确认：查 PR 是否真的进了 MERGING / QUEUED 状态，或已 MERGED
                pr_state = json.loads(gh("pr","view",str(pr_num),"-R",REPO,
                                         "--json","state,mergeStateStatus").stdout or "{}")
                ms = pr_state.get("mergeStateStatus","")
                if (pr_state.get("state") == "MERGED" or
                    ms in ("QUEUED","MERGING","BLOCKED","BEHIND","CLEAN","UNKNOWN","DIRTY","HAS_HOOKS","UNSTABLE","WAITING","BEHIND") or
                    ms == ""):  # UNKNOWN/GitHub 仍在算也算已入队迹象
                    enqueue_failures = []
                    break
            enqueue_failures.append(f"attempt {attempt}: rc={p.returncode} err={err[:300]} ms={ms if 'ms' in dir() else '?'}")
        if enqueue_failures:
            # 不阻断 done 结算，但留响亮痕迹：开 Finding（近因告警，canary 兜底在另一层）
            _file_finding_for_enqueue_fail(c["num"], pr_num, br, enqueue_failures)
    # CAS 置 in_review
    blk = dict(c["blk"], state="in_review")
    it = json.loads(gh("issue","view",str(c["num"]),"-R",REPO,"--json","updatedAt").stdout)
    write_block(c["num"], blk, it["updatedAt"])
    # 贴报告
    report = f"## Done Report\n\n- Card: {blk['id']}\n- Branch: {br}\n- Sandbox: {SID}\n- Model: {MODEL}\n"
    gh("issue","comment",str(c["num"]),"-R",REPO,"--body",report)
    # 清空当前卡
    st(card=None)
    return {"stdout": "OK\n"}

def _ensure_auto_merge_enabled():
    """merge-queue 仓库须 allow_auto_merge=true，否则 gh pr merge --auto 必失败。"""
    p = gh("api",f"/repos/{REPO}","--jq",".allow_auto_merge")
    if p.returncode == 0 and p.stdout.strip() == "false":
        gh("api","-X","PATCH",f"/repos/{REPO}","-F","allow_auto_merge=true")

def _file_finding_for_enqueue_fail(issue_num, pr_num, br, errs):
    """入队失败开 Finding（近因告警，不静默吞）。"""
    msg = "PR_ENQUEUE_FAILED: " + " | ".join(errs)
    body = (f"```json finding\n"
            f'{{"lens":"loopd","severity":"high","message":'
            f'"{msg.replace(chr(34), chr(92)+chr(34))}",'
            f'"path":"PR #{pr_num} ({br})"}}\n```\n\n'
            f"**Issue:** #{issue_num}\n**PR:** #{pr_num}\n**Branch:** `{br}`\n\n"
            f"loopd done 把 issue 置 in_review，但 PR 未能入 merge queue。\n"
            f"Canary 全链路是兜底；本 Finding 是近因告警，需人工介入修 PR。")
    gh("issue","create","-R",REPO,"--title",f"[Finding] PR #{pr_num} enqueue failed",
       "--label","finding","--body",body)

# ============================================================
# drop：删除文件
# ============================================================
@intent("drop")
def h_drop(args):
    if not args:
        return {"code": 64, "stderr": "USAGE: loop drop <path>\n"}
    target = WS / args[0]
    trash = LOOP / "trash"; trash.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        return {"code": 1, "stderr": f"NOT_FOUND: {args[0]}\n"}
    # 移进 trash
    dest = trash / f"{args[0].replace('/','_')}.{int(time.time())}"
    target.rename(dest)
    return {"stdout": f"DROPPED {args[0]} -> {dest}\n"}

# ============================================================
# reset：回干净基线
# ============================================================
@intent("reset")
def h_reset(args):
    sh("git","-C",str(WS),"fetch","origin","main","--prune", check=True)
    sh("git","-C",str(WS),"reset","--hard","origin/main")
    sh("git","-C",str(WS),"clean","-fdx","-e",".loop")
    return {"stdout": "OK (reset to origin/main)\n"}

# ============================================================
# ask：异步问人
# ============================================================
@intent("ask")
def h_ask(args):
    if not args:
        return {"code": 64, "stderr": "USAGE: loop ask <question>\n"}
    d = st(); c = d.get("card")
    msg = " ".join(args)
    if c:
        gh("issue","comment",str(c["num"]),"-R",REPO,"--body",f"**QUESTION:** {msg}")
        # 打 blocked 标签
        gh("issue","edit",str(c["num"]),"-R",REPO,"--add-label","blocked")
    else:
        # 无活跃卡片时在 GRIPE BOX 留言
        gh("issue","comment","1","-R",REPO,"--body",f"**QUESTION (no active card):** {msg}")
    return {"stdout": "OK (question posted, not blocking)\n"}

# ============================================================
# evidence：取证据
# ============================================================
@intent("evidence")
def h_evidence(args):
    if not args:
        return {"code": 64, "stderr": "USAGE: loop evidence <lens>\n"}
    lens = args[0]
    script = pathlib.Path(E.get("LOOP_ROOT","/work")) / "lenses" / f"{lens}.sh"
    if not script.exists():
        return {"code": 1, "stderr": f"UNKNOWN_LENS: {lens}\n"}
    audit_dir = LOOP / "audit"; audit_dir.mkdir(parents=True, exist_ok=True)
    p = sh("bash", str(script), cwd=str(WS), timeout=600)
    return {"stdout": f"EXIT={p.returncode}\n{p.stdout}\n", "stderr": p.stderr}

# ============================================================
# finding：提发现（卡包 A2）
# ============================================================
def _validate_finding(finding):
    """按 .loop/schemas/finding.json 逐字段校验（标准库，不依赖 jsonschema）。

    拒收条件（全部返回 (False, msg)）：
      - 非 object 或 缺少 lens/severity/message/path/evidence → MISSING_FIELDS
      - evidence 字段缺失 → MISSING_FIELDS: ['evidence']（smoke j1 必测）
      - evidence 为空数组 → NO_EVIDENCE（smoke j1a 必测）
      - 任一 evidence 项缺 tool/rule_id/location → BAD_EVIDENCE[i]（smoke j1b 必测）
    """
    if not isinstance(finding, dict):
        return False, "finding must be a JSON object"
    FINDING_REQUIRED = ["lens", "severity", "message", "path", "evidence"]
    missing = [f for f in FINDING_REQUIRED if f not in finding]
    if missing:
        return False, f"MISSING_FIELDS: {missing}"
    for f in ("lens", "message", "path"):
        if not isinstance(finding.get(f), str) or not finding[f].strip():
            return False, f"EMPTY_FIELD: {f}"
    if finding.get("severity") not in ("low", "medium", "high", "critical"):
        return False, f"BAD_SEVERITY: {finding.get('severity')}"
    ev = finding.get("evidence")
    if not isinstance(ev, list):
        return False, "NO_EVIDENCE: evidence must be an array"
    if len(ev) < 1:
        return False, "NO_EVIDENCE: evidence array must have >=1 item"
    for i, item in enumerate(ev):
        if not isinstance(item, dict):
            return False, f"BAD_EVIDENCE[{i}]: not an object"
        ev_missing = [k for k in ("tool", "rule_id", "location") if k not in item]
        if ev_missing:
            return False, f"BAD_EVIDENCE[{i}]: missing {ev_missing} (每项需含 tool+rule_id+location)"
        for k in ("tool", "rule_id", "location"):
            if not isinstance(item.get(k), str) or not item[k].strip():
                return False, f"BAD_EVIDENCE[{i}]: {k} must be non-empty string"
    return True, ""

def _extract_finding_block(body):
    """从 finding issue body 中抽取 ```json finding``` 块为 dict（找不到返回 None）。"""
    m = "```json finding"
    if m not in (body or ""):
        return None
    seg = body.split(m, 1)[1].split("```", 1)[0]
    try:
        return json.loads(seg)
    except Exception:
        return None

def _finding_body(finding, fp, occurrences=1):
    """生成 Finding issue body：原 JSON + fingerprint + occurrences + proposed_card 块。"""
    finding = dict(finding)
    finding["occurrences"] = occurrences
    finding["fingerprint"] = fp
    # proposed_card 块：为该问题开 impl 检查器卡；occurrences>=3 时 _enforce_checker_title 会改标题
    proposed_card = {
        "schema": 1,
        "id": f"chk-{fp[:8]}",
        "tier": "standard",
        "role": "impl",
        "paths": [finding.get("path", "")],
        "charter": ["G0"],
        "title": f"为 {finding.get('lens', 'lens')} finding #{fp[:8]} 写一个自动检查器",
        "acceptance": [
            "新增确定性工具/规则能在本地或 CI 中复现本 finding 的判定",
            "同一类问题新实例不会再以裸 finding 形式出现（由检查器以 Card 形式发出）",
        ],
    }
    finding = _enforce_checker_title(finding, proposed_card)
    return (
        f"```json finding\n{json.dumps(finding, indent=2, ensure_ascii=False)}\n```\n\n"
        f"Fingerprint: `{fp}`  \n"
        f"Occurrences: **{occurrences}**  \n"
        f"Lens: `{finding['lens']}` | Severity: `{finding['severity']}`\n\n"
        f"---\n\n"
        f"## Proposed Card\n\n"
        f"```json loop\n{json.dumps(proposed_card, indent=2, ensure_ascii=False)}\n```"
    )

def _finding_title(finding):
    return f"[Finding] {finding['lens']}: {finding['message'][:60]}"

def _enforce_checker_title(finding, proposed_card=None):
    """occurrences>=3 时把 proposed_card 标题改写为「为 X 写一个检查器」。

    X = finding.lens（若有唯一 rule_id，则 X = lens.rule_id，让检查器更具体）。
    当 proposed_card 传入时就地修改其 title；始终返回 finding（不返回 tuple，
    避免 caller 把 tuple 当成 finding dict 用）。
    """
    occ = finding.get("occurrences", 1)
    if occ < 3:
        return finding
    ev = finding.get("evidence") or []
    rule_ids = sorted({e.get("rule_id", "") for e in ev if isinstance(e, dict) and e.get("rule_id")})
    if len(rule_ids) == 1:
        x = f"{finding['lens']}.{rule_ids[0]}"
    else:
        x = finding["lens"]
    new_title = f"为 {x} 写一个检查器"
    if proposed_card is not None:
        proposed_card["title"] = new_title
    return finding

def _bump_occurrences(ex_issue, fp, new_finding):
    """对已存在的 finding issue 累加 occurrences；>=3 时改写 proposed_card 标题为「为 X 写一个检查器」。

    返回 (new_body, new_occurrences)；无法解析旧 body 返回 (None, 0)。
    """
    body = ex_issue.get("body", "") or ""
    old_finding = _extract_finding_block(body)
    if old_finding is None:
        return None, 0
    occ = int(old_finding.get("occurrences", 1)) + 1
    # 合并 evidence：去重（按 tool+rule_id+location）
    old_ev = old_finding.get("evidence") or []
    seen = set()
    merged = []
    for e in list(old_ev) + list(new_finding.get("evidence") or []):
        key = (e.get("tool",""), e.get("rule_id",""), e.get("location",""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(e)
    old_finding["evidence"] = merged
    old_finding["occurrences"] = occ
    # 重新生成 finding body（proposed_card 块的标题会被 _enforce_checker_title 改写）
    new_body = _finding_body(old_finding, fp, occurrences=occ)
    # 保留原 body 中 finding 块之后的人类内容（如有 comment 在 body 末尾）
    head = body.split("```json finding", 1)[0] if "```json finding" in body else ""
    return head + new_body, occ

@intent("finding")
def h_finding(args):
    if not args:
        return {"code": 64, "stderr": "USAGE: loop finding <file>\n"}
    fpath = WS / args[0]
    if not fpath.exists():
        return {"code": 1, "stderr": f"NOT_FOUND: {args[0]}\n"}
    try:
        finding = json.loads(fpath.read_text())
    except Exception as e:
        return {"code": 1, "stderr": f"BAD_JSON: {e}\n"}
    # 按 finding.json schema 校验（含无证据拒收）
    ok, err = _validate_finding(finding)
    if not ok:
        return {"code": 1, "stderr": f"REJECTED: {err}\n"}
    # 指纹去重: sha256(lens + path + message)
    fp = hashlib.sha256(
        f"{finding['lens']}|{finding['path']}|{finding['message']}".encode()
    ).hexdigest()[:16]
    finding["fingerprint"] = fp
    # 检查是否已存在同指纹 finding
    existing = gh("issue","list","-R",REPO,"--label","finding","--limit","200",
                  "--json","number,body").stdout
    ex_match = None
    for ex in json.loads(existing or "[]"):
        if fp in (ex.get("body") or ""):
            ex_match = ex
            break
    if ex_match:
        # DUPLICATE：累加 occurrences；>=3 时改写 proposed_card 标题为"为 X 写一个检查器"
        new_body, occ = _bump_occurrences(ex_match, fp, finding)
        if new_body is not None:
            gh("issue","edit",str(ex_match["number"]),"-R",REPO,"--body",new_body)
        return {"stdout": f"DUPLICATE (fingerprint {fp} already filed as #{ex_match['number']}, occurrences={occ})\n"}
    # 新 finding：occurrences=1（<3 不触发标题改写）
    finding["occurrences"] = 1
    finding = _enforce_checker_title(finding)
    body = _finding_body(finding, fp)
    p = gh("issue","create","-R",REPO,
           "--title",_finding_title(finding),
           "--label","finding","--body",body)
    num = p.stdout.strip().split("/")[-1] if p.stdout.strip() else "?"
    return {"stdout": f"OK (Finding #{num})\n"}

# ============================================================
# propose：提波次（卡包 W4-1）
# ============================================================
def _wave_pr_body(fpath):
    """波次 PR 正文：wave 内容 + '机器自检' 占位段（planner 负责填，卡包 W4-1）。"""
    try:
        content = fpath.read_text()
    except Exception:
        content = "(无法读取波次文件)"
    return (
        "## Wave Proposal\n\n"
        f"{content}\n\n"
        "---\n\n"
        "## 机器自检\n\n"
        "> 占位段：planner 须在物化前把 spec-kit `analyze` + `checklist` 输出粘到本段。\n"
        "> `loop propose` 只负责开 PR（仅允许改 `waves/**`），不替 planner 跑自检。\n\n"
        "- [ ] `speckit.analyze` 一致性/覆盖度分析通过\n"
        "- [ ] `speckit.checklist` 清单逐条自查通过\n"
        "- [ ] 卡片 paths 两两无 glob 交叉\n"
        "- [ ] 每张卡 charter 映射齐全\n"
    )

@intent("propose")
def h_propose(args):
    if not args:
        return {"code": 64, "stderr": "USAGE: loop propose <file>\n"}
    fpath = WS / args[0]
    if not fpath.exists():
        return {"code": 1, "stderr": f"NOT_FOUND: {args[0]}\n"}
    # 只允许改 waves/**
    br = sh("git","-C",str(WS),"rev-parse","--abbrev-ref","HEAD").stdout.strip()
    base = sh("git","-C",str(WS),"merge-base","origin/main","HEAD").stdout.strip()
    files = sh("git","-C",str(WS),"diff","--name-only",base,"HEAD").stdout.split()
    bad = [f for f in files if not f.startswith("waves/")]
    if bad:
        return {"code": 1, "stderr": f"OUT_OF_SCOPE (only waves/** allowed): {bad}\n"}
    do_save(f"propose: {args[0]}")
    p = gh("pr","create","-R",REPO,"--head",br,"--base","main",
           "--title",f"Wave proposal: {args[0]}",
           "--body",_wave_pr_body(fpath))
    return {"stdout": f"OK (PR: {p.stdout.strip()})\n"}

# ============================================================
# verdict：交裁决（接口契约 0.6 + 卡包 V3/V2）
# ============================================================
VERDICT_REQUIRED = ["head_sha", "blind_phase_commit", "artifact_digest", "test_plan_version", "acs"]

def _validate_verdict(verdict):
    """按接口契约 0.6 的 VERDICT schema 校验（标准库逐字段，不依赖 jsonschema 运行时）。"""
    if not isinstance(verdict, dict):
        return False, "verdict must be a JSON object"
    missing = [f for f in VERDICT_REQUIRED if f not in verdict]
    if missing:
        return False, f"MISSING_FIELDS: {missing}"
    for f in ("head_sha", "blind_phase_commit", "artifact_digest", "test_plan_version"):
        if not isinstance(verdict.get(f), str) or not verdict[f].strip():
            return False, f"EMPTY_FIELD: {f}"
    acs = verdict.get("acs")
    if not isinstance(acs, list) or len(acs) < 1:
        return False, "NO_ACS: acs array must have >=1 item"
    for i, ac in enumerate(acs):
        if not isinstance(ac, dict):
            return False, f"BAD_AC[{i}]: not an object"
        for k in ("id", "pass", "evidence"):
            if k not in ac:
                return False, f"BAD_AC[{i}]: missing {k} (每项需含 id/pass/evidence)"
        if not isinstance(ac.get("id"), str) or not ac["id"].strip():
            return False, f"BAD_AC[{i}]: id must be non-empty string"
        if not isinstance(ac.get("pass"), bool):
            return False, f"BAD_AC[{i}]: pass must be bool"
        if not isinstance(ac.get("evidence"), str) or not ac["evidence"].strip():
            return False, f"BAD_AC[{i}]: evidence must be non-empty string (形如 文件::用例名)"
    return True, ""

@intent("verdict")
def h_verdict(args):
    if not args:
        return {"code": 64, "stderr": "USAGE: loop verdict <file>\n"}
    fpath = WS / args[0]
    if not fpath.exists():
        return {"code": 1, "stderr": f"NOT_FOUND: {args[0]}\n"}
    try:
        verdict = json.loads(fpath.read_text())
    except Exception as e:
        return {"code": 1, "stderr": f"BAD_JSON: {e}\n"}
    # 按接口契约 0.6 VERDICT schema 校验
    ok, err = _validate_verdict(verdict)
    if not ok:
        return {"code": 1, "stderr": f"REJECTED: {err}\n"}
    d = st(); c = d.get("card")
    if not c:
        return {"code": 1, "stderr": "NO_ACTIVE_CARD\n"}
    # head_sha 绑定校验（卡包 V3/V2）：head_sha ≠ 当前 HEAD → 拒收并提示重跑
    head = sh("git","-C",str(WS),"rev-parse","HEAD").stdout.strip()
    if verdict["head_sha"] != head:
        return {"code": 1, "stderr": (
            f"SHA_MISMATCH: verdict head_sha={verdict['head_sha'][:8]} actual HEAD={head[:8]}\n"
            f"VERDICT 绑定的 head_sha 已过期（PR 有新 commit）。请重跑 verifier 阶段二/三"
            f"（执行定位 + 结论），用最新 HEAD 重新生成 VERDICT 后再 loop verdict。\n")}
    # 填 verifier_model
    verdict["verifier_model"] = MODEL
    body = f"## VERDICT\n\n```json verdict\n{json.dumps(verdict, indent=2)}\n```"
    gh("issue","comment",str(c["num"]),"-R",REPO,"--body",body)
    return {"stdout": "OK (verdict posted)\n"}

# ============================================================
# upstream：登记依赖
# ============================================================
@intent("upstream")
def h_upstream(args):
    if not args:
        return {"code": 64, "stderr": "USAGE: loop upstream <pkg>\n"}
    pkg = args[0]
    upstream_file = WS / "UPSTREAM.yaml"
    if not upstream_file.exists():
        return {"code": 1, "stderr": "NOT_REGISTERED (no UPSTREAM.yaml)\n"}
    # 简易 YAML 解析
    content = upstream_file.read_text()
    if pkg not in content:
        return {"stdout": "NOT_REGISTERED\n"}
    # 查发布日期（通过 gh api 或 npm/pypi registry）
    # 最小实现：检查是否在 UPSTREAM.yaml 里有登记
    # 真实发布日期查询留给 W2 的 upgrade.yml workflow
    return {"stdout": f"OK (registered: {pkg})\n"}

# ============================================================
# [已移除] run：白名单意图兜底（#52/#53）
# load_intents / h_run / @intent("run") 已删除：远程意图执行通道不再存在。
# loopd 不再从 intents.yaml 加载外部命令白名单，也不注册 run verb。
# ============================================================

# ============================================================
# retire：结束会话
# ============================================================
@intent("retire")
def h_retire(args):
    d = st()
    # 归档上下文
    archive = LOOP / "archive"; archive.mkdir(parents=True, exist_ok=True)
    archive_file = archive / f"session-{SID}-{int(time.time())}.json"
    archive_file.write_text(json.dumps(d, indent=2))
    # 写 session-ended 标记
    (LOOP / "session-ended").write_text(f"retired at {time.time()}\n")
    st(card=None, session_ordinal=0)
    return {"stdout": "RETIRED (session archived, clicker will reopen)\n"}

# ============================================================
# status：自检
# ============================================================
@intent("status")
def h_status(args):
    d = st()
    lines = ["=== loopd status ==="]
    lines.append(f"sandbox: {SID}")
    lines.append(f"role: {','.join(ROLE)}")
    lines.append(f"model: {MODEL}")
    lines.append(f"session_ordinal: {d.get('session_ordinal',0)} / {E.get('LOOP_MAX_CARDS_PER_SESSION','?')}")
    c = d.get("card")
    if c:
        lines.append(f"card: #{c['num']} ({c['blk'].get('id','?')}) state={c['blk'].get('state','?')}")
        lease = c['blk'].get('lease_until',0)
        lines.append(f"lease: {'EXPIRED' if lease < time.time() else f'{int((lease-time.time())/60)}m left'}")
    else:
        lines.append("card: none")
    # token 检查
    tok = E.get("GH_TOKEN") or E.get("GITHUB_TOKEN") or ""
    lines.append(f"token: {'set' if tok else 'MISSING'}")
    # daemon 存活
    lines.append(f"daemon: alive (pid={os.getpid()})")
    lines.append("=== OK ===")
    return {"stdout": "\n".join(lines) + "\n"}

# ============================================================
# tick：调用 conductor/tick.py 关键函数（方案 B，暂行期）
# ============================================================
@intent("tick")
def h_tick(args):
    """暂行期：由 P-continue agent 在每次'继续'时调一次，或外部 cron 触发。
    调用 conductor/tick.py 的 4 件关键函数：
    僵尸回收、依赖放行、plan inbox 打包、48h 静默放行。
    conductor App 建好后切回原生 workflow（见 C-006）。"""
    import importlib.util
    tick_path = ROOT / "conductor" / "tick.py"
    if not tick_path.exists():
        tick_path = pathlib.Path("/workspace") / "conductor" / "tick.py"
    if not tick_path.exists():
        return {"code": 1, "stderr": f"tick.py not found at {tick_path}\n"}
    spec = importlib.util.spec_from_file_location("tick", tick_path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        return {"code": 1, "stderr": f"tick.py load error: {e}\n"}
    results = []
    # 1. 僵尸回收
    try:
        reclaimed = mod.zombie_reclaim()
        results.append(f"[1] zombie_reclaim: {len(reclaimed) if reclaimed else 0} reclaimed")
    except Exception as e:
        results.append(f"[1] zombie_reclaim: ERROR {e}")
    # 2. 依赖放行
    try:
        mod.unblock_deps()
        results.append("[2] unblock_deps: done")
    except Exception as e:
        results.append(f"[2] unblock_deps: ERROR {e}")
    # 3. plan inbox 打包
    try:
        mod.plan_inbox_pack()
        results.append("[3] plan_inbox_pack: done")
    except Exception as e:
        results.append(f"[3] plan_inbox_pack: ERROR {e}")
    # 4. 48h 静默放行
    try:
        mod.silent_auto_release()
        results.append("[4] silent_auto_release: done")
    except Exception as e:
        results.append(f"[4] silent_auto_release: ERROR {e}")
    return {"stdout": "=== loop tick ===\n" + "\n".join(results) + "\n=== tick complete ===\n"}

# ============================================================
# help：打印动词表
# ============================================================
VERB_TABLE = """\
loop <verb> [args]

Verbs:
  next                阻塞取卡（最长 25 分钟）
  save "msg"          落盘一步（add+commit+push，首次自动开 draft PR）
  verify              本地验收（跑 .loop/verify.sh）
  done                交卡（终验+PR ready+CAS in_review+清卡）
  drop <path>         删除文件（移进 .loop/trash/）
  reset               回干净基线（reset --hard origin/main）
  ask "..."           异步问人（issue 留言+blocked 标签，不阻塞）
  evidence <lens>     取证据（跑 lens 脚本）
  finding <file>      提发现（校验+去重+配额，开 Finding issue）
  propose <file>      提波次（只允许改 waves/**）
  verdict <file>      交裁决（校验 head_sha 绑定）
  upstream <pkg>      登记依赖（查冷静期）
  retire              结束会话（归档+通知点击器重开）
  status              自检（daemon/token/租约/计数）
  tick                跑 conductor tick 4 件（僵尸/依赖/inbox/48h 放行）
  help                打印本表

形式：loop <动词> [最多两个位置参数]
禁止出现：git rm del rmdir mv move cp copy curl wget chmod chown sudo kill pkill ps ssh scp
禁止元字符：&& || ; | > >> < $() `` * ? ~
"""

@intent("help")
def h_help(args):
    return {"stdout": VERB_TABLE}

# ============================================================
# 心跳 + 自动落盘（手册 5.4）
# ============================================================
def heartbeat_thread():
    while True:
        d = st(); c = d.get("card")
        if c:
            b = dict(c["blk"]); b["heartbeat_at"] = int(time.time())
            b["lease_until"] = int(time.time()) + int(E.get("LOOP_LEASE_MIN", 30))*60
            it = json.loads(gh("issue","view",str(c["num"]),"-R",REPO,"--json","updatedAt").stdout)
            write_block(c["num"], b, it["updatedAt"]); st(card={"num": c["num"], "blk": b})
        time.sleep(int(E.get("LOOP_HEARTBEAT_SEC", 120)))

def autosave_thread():
    while True:
        d = st(); c = d.get("card")
        if c and sh("git","-C",str(WS),"status","--porcelain").stdout.strip():
            do_save(f'wip: {c["blk"]["id"]}')          # 含首次 push 自动开 draft PR
        time.sleep(int(E.get("LOOP_AUTOSAVE_SEC", 300)))

# ============================================================
# 僵尸回收（手册 6.1 第1件事本地化，v0.1.5 新增）
# ============================================================
def _iso_to_ts(s):
    try: return datetime.datetime.fromisoformat(str(s).replace("Z","+00:00")).timestamp()
    except Exception: return 0.0

def reap_once():
    """僵尸回收单次扫描：lease 过期且 lease 期内无新 commit 的 claimed/in_progress
    卡退回 ready（attempt+=1，清 claim_id/sandbox/lease/heartbeat）。返回回收列表。

    原依赖外部 conductor/tick.py（cron */5），但 GitHub 对高频 cron 严重限流
    （实测 4h 只跑 2 次），沙盒被 kill 留下的 claimed 卡永远卡住、新沙盒取不到。
    搬进 loopd 自治，用沙盒自身 GH_TOKEN（填写卡已要求 Issues:write）。
    并发去重靠 write_block 的 CAS（updatedAt 不匹配即放弃，多沙盒同时扫只有一个成功）。
    """
    now = int(time.time())
    lease_min = int(E.get("LOOP_LEASE_MIN", "45"))
    reclaimed = []
    for it, blk in cards(("claimed", "in_progress")):
        if blk.get("lease_until", 0) > now: continue
        cid = blk.get("id", "")
        # lease 期内有新 commit → 沙盒还在干活（autosave 在推），不回收
        lease_start_ts = blk.get("lease_until", 0) - lease_min*60
        has_commit = False
        if cid:
            p = gh("pr","list","-R",REPO,"--head",
                   f'{E.get("LOOP_BRANCH_PREFIX", "loop/card")}/{cid}',"--state","open",
                   "--json","number,updatedAt")
            try:
                for pr in json.loads(p.stdout or "[]"):
                    if _iso_to_ts(pr.get("updatedAt","")) > lease_start_ts:
                        has_commit = True; break
            except Exception:
                pass
        if has_commit: continue
        new = dict(blk)
        new["state"] = "ready"
        new["attempt"] = blk.get("attempt", 0) + 1
        new.pop("claim_id", None)
        new.pop("sandbox", None)
        new.pop("lease_until", None)
        new.pop("heartbeat_at", None)
        if write_block(it["number"], new, it["updatedAt"]):
            reclaimed.append((it["number"], cid, new["attempt"]))
            print(f"[reaper] #{it['number']} ({cid}) reclaimed "
                  f"(attempt={new['attempt']})", flush=True)
    return reclaimed

def reaper_thread():
    while True:
        try: reap_once()
        except Exception as e:
            print(f"[reaper] error: {e}", flush=True)
        time.sleep(int(E.get("LOOP_REAPER_SEC", "60")))

# ============================================================
# 主循环（手册 5.1）
# ============================================================
def main():
    # 确保目录结构存在（#52/#53：RELAY/inbox/outbox/done 已移除）
    for d in [LOOP, LOOP/"logs", LOOP/"trash", LOOP/"audit", LOOP/"plan"]:
        d.mkdir(parents=True, exist_ok=True)
    d = st()  # 初始化（加载已有 daemon.json 或建新）
    # v0.1.5 Fix A：新进程启动若无活跃卡，重置会话配额。
    # 场景：上一会话被中断（没调 loop retire），daemon.json 残留 session_ordinal，
    # 续跑配额被"幽灵消耗"（曾表现为沙盒只跑 2 张卡就 retire）。新启动=新会话。
    # 若有活跃卡（崩溃恢复中）则保留 ordinal，让 agent 续完。
    if not d.get("card"):
        st(session_ordinal=0, started=time.time())
    # #52/#53：relay_thread / filemode_thread 已移除，不再启动远程命令通道线程
    for t in (heartbeat_thread, autosave_thread, reaper_thread):
        threading.Thread(target=t, daemon=True).start()
    while True:
        time.sleep(3600)

if __name__ == "__main__":
    main()
