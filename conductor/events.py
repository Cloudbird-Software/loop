#!/usr/bin/env python3
"""conductor/events.py — 事件日志（append-only，W3-9）。

W2 关闭判定要求"事件-投影对账连续 72h diff=0"，底层需要一个可追溯、不可被
覆盖的**事件日志**。本模块提供纯库实现：

  - append_event()   —— 追加（非覆盖）一条事件，每行一条 JSONL；
  - 日志落在 loop-state/events/*.jsonl（经 cas.py 落地 loop-state 分支时使用），
    本地以 LOOP_STATE 为基准目录，缺省 ``.loop/state``；
  - 纯 append（``open(path, "a")``），不读改写，杜绝覆盖式 results 那类丢历史问题。

N31 hard rule：事件日志路径不得落在 .gitignore 覆盖范围内（如 .loop/audit/），
否则 append 的历史会被 git 静默忽略进而造成"假对账"。因此默认根目录固定在
loop-state（分支）的 events/ 之下，本地镜像为 .loop/state/events/（未 ignore）。
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib

# loop-state 分支（状态真源）与 events 子目录（N31：不落 .gitignore 覆盖范围）
LOOP_STATE_BRANCH = "loop-state"
EVENTS_SUBDIR = "events"

# 投影快照在 loop-state 分支下的相对路径（{card_id: state}，对账基线）。
# 每次 sync_to_loop_state 由调用方作为 extra_files 一并写入，供下轮观测差分用。
SNAPSHOT_PATH = "cards/snapshot.json"


def resolve_events_root(root=None):
    """解析事件日志基准目录。

    优先级：显式 root > env LOOP_STATE > .loop/state（未 gitignore）。
    返回值恒为该目录下的 events/ 绝对路径（pathlib.Path）。
    """
    base = root
    if base is None:
        base = os.environ.get("LOOP_STATE") or ".loop/state"
    base_dir = pathlib.Path(base)
    events_dir = base_dir / EVENTS_SUBDIR
    events_dir.mkdir(parents=True, exist_ok=True)
    return events_dir


def append_event(event, root=None, ts=None):
    """追加一条事件（append-only，JSONL 单行），返回写入的文件路径。

    - event：dict（必须可 JSON 序列化）；会在其上补 ``ts``（如未提供则用当前 UTC）。
    - 定位到 ``<root>/events/<YYYYMMDD>.jsonl``，用 ``open(path, "a")`` 追加，
      绝不用 ``"w"``（不覆盖，保留历史）。
    - 返回写入的文件路径。
    """
    if not isinstance(event, dict):
        raise TypeError("event must be a dict")

    payload = dict(event)
    if ts is not None:
        payload.setdefault("ts", ts)
    if "ts" not in payload:
        payload.setdefault(
            "ts", datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        )

    events_dir = resolve_events_root(root)
    filename = payload.get("_day") or datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    path = events_dir / f"{filename}.jsonl"

    # append-only：'a' 追加，绝不覆盖；N31 由 path 位于 loop-state/events 之下保证。
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return str(path)


def load_events(glob_dir):
    """读取某 events 目录下全部 JSONL，返回事件列表（行级容错：坏行跳过但计入 bad）。"""
    rows = []
    bad = 0
    path = pathlib.Path(glob_dir)
    for f in sorted(path.glob("*.jsonl")):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    bad += 1
        except OSError:
            bad += 1
    return rows, bad


def emit_transition(card_id, from_state, to_state, actor="loop-conductor",
                    repo=None, root=None, **extra):
    """记录一次真实状态迁移（control-plane 观测到 from→to）到事件日志。

    生成带迁移语义的事件（transition='from->to'），追加到本地
    <root>/events/<YYYYMMDD>.jsonl（append-only）。之后由 sync_to_loop_state 持久化
    到 loop-state 分支，供 reconcile 对账。返回事件字典（便于单测断言）。
    """
    if not isinstance(card_id, (str, int)):
        raise TypeError("card_id must be str/int")
    ev = {
        "event": "state_transition",
        "action": "state_transition",
        "card": card_id,
        "from": from_state,
        "to": to_state,
        "transition": f"{from_state or '*'}->{to_state or '?'}".replace("None->", "*->"),
        "actor": actor,
    }
    if repo is not None:
        ev["repo"] = repo
    ev.update(extra)
    append_event(ev, root=root)
    return ev


def _branch_request(owner_repo, token, url_suffix):
    """对 loop-state 分支 API 的一次 GET（JSON 返回）。网络/解析失败抛异常，交由调用方处理。"""
    import json as _json
    import urllib.request

    req = urllib.request.Request("https://api.github.com" + url_suffix)
    if token:
        req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req) as r:
        return _json.loads(r.read().decode("utf-8"))


def read_branch_file(owner_repo, token=None, path=SNAPSHOT_PATH, ref="heads/loop-state"):
    """读 loop-state 分支某文本文件内容；不存在/失败返回 None（缺省基线，非错误）。"""
    import json as _json
    try:
        sha = _branch_request(owner_repo, token, f"/git/refs/heads/{ref}")["object"]["sha"]
        tree = _branch_request(owner_repo, token, f"/git/trees/{sha}?recursive=1")
    except Exception:
        return None
    for t in tree.get("tree", []):
        if t.get("type") != "blob" or t.get("path") != path:
            continue
        try:
            blob = _branch_request(owner_repo, token, f"/git/blobs/{t['sha']}")
            from base64 import b64decode
            return b64decode(blob.get("content", "")).decode("utf-8", "replace")
        except Exception:
            return None
    return None


def sync_to_loop_state(owner_repo, token=None, root=None, message=None, extra_files=None):
    """把本地 <root>//events/*.jsonl 持久化到 loop-state/events/ 分支（N31 持久化）。

    使用 cas.update_files（多文件、不发射事件）读-CAS 追加。**按天合并**：本地某日
    events/<day>.jsonl 会与分支上已有同名文件**拼接**而非覆盖，保证跨 CI job（每次
    全新 checkout 只见当日本地）历史事件不丢、可持续累积（72h close-out 所需）。
    返回新 ref sha；本地与 extra 均无内容时返回 None（不写分支，不算错）。
    """
    from conductor import cas

    events_dir = resolve_events_root(root)
    out = {}
    for f in sorted(pathlib.Path(events_dir).glob("*.jsonl")):
        try:
            local = f.read_text(encoding="utf-8").rstrip("\n")
            if not local:
                continue
            rel = f"events/{f.name}"
            existing = read_branch_file(owner_repo, token, path=rel) or ""
            existing = existing.rstrip("\n")
            out[rel] = f"{existing}\n{local}\n" if existing else f"{local}\n"
        except OSError:
            continue
    for p, c in (extra_files or {}).items():
        out[p] = c
    if not out:
        return None
    base = cas.current_sha(owner_repo, ref="heads/loop-state", token=token)
    if base is None:
        raise RuntimeError("loop-state ref not found; cannot persist events (CAS root missing)")
    return cas.update_files(
        owner_repo, base, out,
        message=message or "loop: persist event log (append-only, N31)",
        ref="heads/loop-state", token=token,
    )


def load_json_from_loop_state(owner_repo, token=None, path=SNAPSHOT_PATH,
                              ref="heads/loop-state"):
    """读 loop-state 分支下某 JSON 文件内容，解析失败/不存在返回 None（缺省基线）。"""
    import json as _json
    text = read_branch_file(owner_repo, token, path=path, ref=ref)
    if text is None:
        return None
    try:
        return _json.loads(text)
    except ValueError:
        return None


def load_from_loop_state(owner_repo, token=None, ref="heads/loop-state"):
    """从 loop-state/events/*.jsonl 分支读取事件，返回 (rows, bad)。

    先取分支递归树，再取每个 events/*.jsonl blob 内容并逐行解析（坏行计入 bad）。
    每行 JSON 解析容错，与 load_events 语义一致。
    """
    import json as _json
    import urllib.request
    from conductor import cas

    def _get(url):
        req = urllib.request.Request("https://api.github.com" + url)
        if token:
            req.add_header("Authorization", f"token {token}")
        req.add_header("Accept", "application/vnd.github+json")
        with urllib.request.urlopen(req) as r:
            return _json.loads(r.read().decode("utf-8"))

    try:
        branch = _get(f"/repos/{owner_repo}/git/refs/heads/{ref}")
    except Exception:
        return [], 0
    sha = branch["object"]["sha"]
    tree = _get(f"/repos/{owner_repo}/git/trees/{sha}?recursive=1")
    rows, bad = [], 0
    for t in tree.get("tree", []):
        if t.get("type") != "blob" or not t.get("path", "").startswith("events/"):
            continue
        try:
            blob = _get(f"/repos/{owner_repo}/git/blobs/{t['sha']}")
            content = blob.get("content", "")
            if not content:
                continue
            from base64 import b64decode
            text = b64decode(content).decode("utf-8", "replace")
        except Exception:
            bad += 1
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(_json.loads(line))
            except ValueError:
                bad += 1
    return rows, bad