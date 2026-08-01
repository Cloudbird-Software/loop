#!/usr/bin/env python3
"""conductor/audit.py — 审计分片执行器（W0-3：从 audit.yml Step 2 内联 heredoc 抽出）。

原先整段审计逻辑埋在 .github/workflows/audit.yml 的 `python3 << 'PYEOF'` heredoc
里——无法被 import、无法被单元测试、改一行就要靠 CI 试错。W0-3 把这段逻辑原样搬到
本模块，audit.yml Step 2 改为薄壳 `python3 -m conductor.audit`，使审计逻辑可被
conductor.* 其它模块复用、可被 tests/ 覆盖，且与 conductor/tick.py 共享同一份
sys.path 修复（W0-3 根因修复）。

行为与原 heredoc 基本一致，唯一有意加强：lens 脚本非 0 退出也计入失败（N11
不静默吞错，Copilot review 建议采纳）。
  - 读 .loop/audit/today_shards.json（由 tick.audit_shard_rotate 产出）
  - 逐 shard：git diff --name-only last_audited_sha..HEAD 取变更路径
  - 逐 lens：调 lenses/<lens>.sh <ev_in.json> <ev_out.json>，解析结果
  - fingerprint 去重 + 配额控制 + occurrences bump
  - 新 finding → create_finding 开 GitHub issue（或复用已 open 的）
  - 写 .loop/audit/run_summary.json + new_findings.json
  - 缺脚本的 lens 不静默跳过（R14-1）：循环结束 exit 1
  - lens 脚本非 0 退出同样计入失败（N11 不静默吞错）：循环结束 exit 1

退出码：缺脚本 lens 或 lens 非 0 退出 → exit 1（不静默跳过）；否则 exit 0。
"""
import json, pathlib, subprocess, datetime, tempfile, sys, os

# W0-3 根因修复：直接运行 `python conductor/audit.py` 时 sys.path[0] 是 conductor/
# 而非仓库根，导致下方延迟导入 `from conductor.tick import ...` 与
# `from conductor.findings import ...` 抛 ModuleNotFoundError（与 tick.py 同一根因；
# Copilot round-4 review 指出：docstring 声称共享 sys.path 修复但本文件自身缺这层）。
# 把仓库根插入 sys.path，使 conductor.* 包导入在脚本直跑与 `python -m conductor.audit`
# 两种模式下都可用。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _now_iso():
    # aware UTC + 收敛 DeprecationWarning（替代 utcnow().isoformat()+'Z'）
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')


def _now_ts():
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp())


def run_audit_shards():
    """逐片逐 lens 跑审计；返回 (quota_runs, new_findings, lens_failures)。

    与 audit.yml 原 heredoc 逐字等价；抽出为函数以便单元测试与复用。
    """
    # 延迟导入：与原 heredoc 一致（在循环内 import）；同时避免模块加载期就触发
    # conductor.tick 的 module-level 副作用（load_policy 等）。
    from conductor.tick import _load_audit_state, _save_audit_state, resolve_loop_root
    from conductor.findings import create_finding, find_open_finding, update_finding, fingerprint

    # 复用 tick.resolve_loop_root() 的优先级（LOOP_ROOT > GITHUB_WORKSPACE > /workspace），
    # 避免 os.environ['LOOP_ROOT'] 在本地/单测未设置时抛 KeyError（CodeQL/Copilot 建议）。
    LOOP = resolve_loop_root()
    TODAYS = LOOP / '.loop' / 'audit' / 'today_shards.json'
    QUOTA_RUNS = []
    NEW_FINDINGS = []
    LENS_FAILURES = []   # 缺脚本的 lens 列表：循环结束后若有则整体红
    if TODAYS.exists():
        cfg = json.loads(TODAYS.read_text())
        quota_left = cfg.get('quota_left', 8)
    else:
        cfg = {'shards': []}
        quota_left = 8
    for sh in cfg.get('shards', []):
        sid = sh['id']
        last_sha = sh.get('last_audited_sha', 'HEAD~1')
        # 取 diff 路径（简化版；实际用 git diff --name-only last_sha..HEAD）
        # Copilot round-5 review：检查 returncode——last_sha 不存在/仓库异常时
        # subprocess.run 不抛异常但返回非 0，若不检查会把 diff_paths 静默降级为空，
        # 导致该 shard 实际有变更但审计输入为空（误漏 finding，N11 假绿风险）。
        try:
            r = subprocess.run(['git', 'diff', '--name-only', last_sha, 'HEAD'],
                               capture_output=True, text=True, cwd=str(LOOP))
            if r.returncode != 0:
                # 非 0 退出：记录 stderr 便于排障。Copilot round-6 review：diff 失败
                # 若仅静默降级为空会让该 shard 审计输入变"无变更"，可能误漏 finding 而
                # workflow 仍 exit 0（假绿）。故把 diff 失败计入失败集合，最终让 main()
                # exit 1；同时 diff_paths 按空继续跑该 shard 的 lens（输出更多诊断信息）。
                print(f'shard {sid}: git diff {last_sha}..HEAD exited {r.returncode}: '
                      f'{(r.stderr or "").strip()}', file=sys.stderr)
                diff_paths = []
                LENS_FAILURES.append((sid, '__git_diff__'))
            else:
                diff_paths = [x for x in r.stdout.splitlines() if x.strip()]
        except Exception as e:
            diff_paths = []
            print(f'shard {sid}: diff failed {e}')
            LENS_FAILURES.append((sid, '__git_diff__'))
        for lens in sh.get('lenses', []):
            script_sh = LOOP / 'lenses' / f'{lens}.sh'
            if not script_sh.exists():
                # R14-1：缺脚本不再静默跳过——记录失败，循环结束后整体 exit 1
                print(f'LENS_NOT_EXECUTED: {lens}')
                LENS_FAILURES.append((sid, lens))
                continue
            # 喂给 lens 的证据 JSON（标准化输入）
            evidence_in = {
                'lens': lens, 'shard': sid,
                'last_audited_sha': last_sha, 'head_sha': 'HEAD',
                'diff_paths': diff_paths,
                'generated_at': _now_iso(),
            }
            with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
                json.dump(evidence_in, f, ensure_ascii=False)
                ev_in = f.name
            with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
                ev_out = f.name
            # 调用 lens 脚本（约定：lens <ev_in.json> <ev_out.json>）
            # 采纳 Copilot 建议：检查 returncode 区分"lens 显式失败(非0退出)"与
            # "脚本崩溃/异常"；前者记入 LENS_FAILURES 以便循环结束后整体红，避免
            # 静默吞错（N11）。保持原 12 空格缩进，修复 c84ec7d 的 IndentationError。
            # 标签用 LENS_FAILED（而非 LENS_NOT_EXECUTED）：脚本已被执行只是失败退出，
            # "NOT_EXECUTED" 会误导定位（Copilot review 建议）。
            try:
                p = subprocess.run(
                    ['bash', str(script_sh), ev_in, ev_out],
                    capture_output=True, text=True, timeout=300,
                    cwd=str(LOOP))
                if p.returncode != 0:
                    msg = (p.stderr or p.stdout or f"LENS_FAILED: {lens} (exit {p.returncode})").strip()
                    print(msg, file=sys.stderr)
                    LENS_FAILURES.append((sid, lens))
                    results = []
                else:
                    try:
                        results = json.loads(pathlib.Path(ev_out).read_text() or '[]')
                    except Exception as e:
                        results = []
            except Exception as e:
                print(f"LENS_FAILED: {lens} ({e})", file=sys.stderr)
                LENS_FAILURES.append((sid, lens))
                results = []
            # fingerprint 去重 + 配额控制
            state = _load_audit_state()
            for r0 in (results if isinstance(results, list) else []):
                if not isinstance(r0, dict):
                    continue
                fp = fingerprint(lens,
                                 r0.get('path', ''),
                                 r0.get('symbol', ''),
                                 r0.get('rule_id', ''))
                if fp in state.get('closed_findings', {}):
                    continue  # stale 已关，不再重开
                meta = state['fingerprints'].setdefault(fp, {
                    'first_seen': _now_ts(),
                    'occurrences': 0, 'severity': r0.get('severity', 'low'),
                })
                meta['occurrences'] += 1
                meta['last_seen'] = _now_ts()
                if 'lens' not in meta:
                    meta['lens'] = lens
                    meta['shard'] = sid
                is_new = 'finding_id' not in meta
                if is_new and state['daily_new_findings'] >= quota_left:
                    continue  # 超配额，跳过
                if is_new:
                    state['daily_new_findings'] += 1
                    # R14-1：先按指纹查重；已有 open finding 则复用其 issue 号并追加评论，
                    # 否则创建真实 GitHub issue，以其编号作为 finding_id 贯穿全流程
                    existing = find_open_finding(fp)
                    if existing:
                        meta['finding_id'] = existing
                        update_finding(existing,
                                       f"occurrences={meta['occurrences']} last_seen={meta['last_seen']} (re-detected)")
                    else:
                        meta['finding_id'] = create_finding(
                            lens=lens,
                            path=r0.get('path', ''),
                            symbol=r0.get('symbol', ''),
                            rule_id=r0.get('rule_id', ''),
                            severity=meta['severity'],
                            raw=r0)
                    state['adoption_log'].append({
                        'ts': _now_ts(),
                        'event': 'opened', 'fp': fp})
                    NEW_FINDINGS.append({
                        'fp': fp, 'lens': lens, 'shard': sid,
                        'severity': meta['severity'], 'occurrences': meta['occurrences'],
                        'raw': r0})
            _save_audit_state(state)
            QUOTA_RUNS.append({'shard': sid, 'lens': lens,
                               'diff_paths_count': len(diff_paths),
                               'results_count': len(results)})
            # 清理临时文件：best-effort，文件可能已被删除或不存在，忽略 FileNotFoundError
            # 即可；其他异常也不应中断审计主流程，故仅记录不抛出（CodeQL：非空 except）。
            for _p in [ev_in, ev_out]:
                try:
                    pathlib.Path(_p).unlink()
                except FileNotFoundError:
                    pass  # 文件已不存在，正常情况
                except OSError as e:
                    print(f"cleanup { _p }: {e}", file=sys.stderr)
    # 汇总输出
    summary = {
        'generated_at': _now_iso(),
        'runs': QUOTA_RUNS,
        'new_findings_count': len(NEW_FINDINGS),
        'new_findings_sample': NEW_FINDINGS[:8],
    }
    outdir = LOOP / '.loop' / 'audit'
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / 'run_summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    (outdir / 'new_findings.json').write_text(json.dumps(NEW_FINDINGS, indent=2, ensure_ascii=False))
    print(f'== runs: {len(QUOTA_RUNS)}; new findings: {len(NEW_FINDINGS)} (quota cap {quota_left}) ==')
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return QUOTA_RUNS, NEW_FINDINGS, LENS_FAILURES


def main():
    """audit.yml Step 2 入口：跑分片 → 缺脚本/diff 失败则 exit 1（R14-1，不静默跳过）。"""
    _runs, _new, lens_failures = run_audit_shards()
    # R14-1：缺脚本即红——循环结束后若有 lens/diff 失败则整体 exit 1（不静默跳过）。
    # 失败集合涵盖"缺脚本"、"脚本非0退出"、"git diff 失败"三类（Copilot round-6：
    # diff 失败也计入，避免审计输入静默降级为空而 workflow 仍 exit 0 的假绿风险）。
    if lens_failures:
        print(f'SHARD_FAILURES ({len(lens_failures)}): {lens_failures}')
        sys.exit(1)


if __name__ == "__main__":
    main()
