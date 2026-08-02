#!/usr/bin/env python3
"""gates/gate_schema_singlesource.py — 校验 schema 单一事实源（W2-5，AC-3）。

gate 契约：exit 0 = 通过，exit 1 = 失败。
作用：conductor/schema_types.py 与 .loop/schemas/state.json 必须保持一致。
如果 schema_types.py 内的类型视图与单一事实源（state.json）漂移（版本号、
字段名集合不一致），本 gate 以非零退出；一致时退出 0。
"""
import json
import os
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, REPO_ROOT)

# 独立读取单一事实源，避免依赖 import 副作用掩盖真实对比。
SCHEMA_PATH = os.path.join(REPO_ROOT, ".loop", "schemas", "state.json")


def _load_source() -> dict:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    try:
        import conductor.schema_types as st
    except Exception as exc:  # 显式失败：模块导入失败视为 gate 失败，不 fail-open
        print(f"FAIL: cannot import conductor.schema_types: {exc}")
        return 1

    source = _load_source()
    src_version = source["properties"]["schema"]["const"]

    diffs = []

    # 1) schema 版本与 source 一致
    if st.SCHEMA_VERSION != src_version:
        diffs.append(
            f"SCHEMA_VERSION mismatch: schema_types={st.SCHEMA_VERSION} "
            f"state.json const={src_version}"
        )

    # 2) SUPPORTED_SCHEMA_VERSIONS 必须 = {N, N-1}
    expected_supported = {int(src_version), int(src_version) - 1}
    if set(st.SUPPORTED_SCHEMA_VERSIONS) != expected_supported:
        diffs.append(
            f"SUPPORTED_SCHEMA_VERSIONS mismatch: schema_types={sorted(st.SUPPORTED_SCHEMA_VERSIONS)} "
            f"expected={sorted(expected_supported)}"
        )

    # 3) 字段名集合必须与 source 的 properties 一致（单一事实源）
    src_card_keys = frozenset(source["properties"].keys())
    if st.SCHEMA_TYPE_CARD_KEYS != src_card_keys:
        excess_schema = sorted(st.SCHEMA_TYPE_CARD_KEYS - src_card_keys)
        excess_src = sorted(src_card_keys - st.SCHEMA_TYPE_CARD_KEYS)
        diffs.append(
            "card-state field set drift: "
            f"schema_types excess={excess_schema}, "
            f"source excess={excess_src}"
        )

    if diffs:
        for d in diffs:
            print(f"FAIL: {d}")
        print("schema single-source divergence detected")
        return 1

    print(
        f"OK: schema single-source consistent "
        f"(version={st.SCHEMA_VERSION}, supported={sorted(st.SUPPORTED_SCHEMA_VERSIONS)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())