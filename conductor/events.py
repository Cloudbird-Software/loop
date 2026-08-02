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