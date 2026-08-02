#!/usr/bin/env python3
"""gates/gate_doc_drift.py —— prompts 文档 vs loopd 注册动词的真相巡检（W1-3 / AC-1..AC-5）。

三方比对：
  1) 从 prompts/*.md 中提取 `loopd <动词>` 引用集合（交流文档"宣称"的动词）；
  2) 解析 loopd/loopd.py 源码中的 @intent("...") 注册动词集合（实现"实际"的动词）；
  3) 对比：prompts 宣称的任何动词若不在实现动词集合内，即为文实漂移 → FAIL（exit 1）。

设计约束：
  - 独立脚本，不 import loopd 内部模块（loopd.py 是承重文件，只读其源码即可，
    避免 import 触发其副作用/依赖）。
  - 快速轻量：仅做两次正则扫描，适合 run_gates.py 的超时限制。
  - 无假绿：漂移即 returncode 非 0；检测源异常（读不到文件 / 提取不到动词）也 FAIL。
  - 工作目录兼容：基于本脚本自身路径定位仓库根，可在仓库根 /workspace 下
    `python3 gates/gate_doc_drift.py` 运行，也可由 run_gates.py 以其它 cwd 调用。
"""
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROMPTS_DIR = os.path.join(REPO_ROOT, "prompts")
LOOPD_SRC = os.path.join(REPO_ROOT, "loopd", "loopd.py")

# 提取 prompts 中 `loopd <动词>`（仅小写字母，与 AC-1 的 grep -oE 'loopd [a-z-]+' 严格一致；
# 大写专有名词如 "loopd CLI" 不属于动词，刻意不纳入，避免误报）
PROMPT_VERB_RE = re.compile(r"\bloopd[ \t]+([a-z][a-z-]*)")
# 提取 loopd.py 中 @intent("verb") 注册的动词
INTENT_RE = re.compile(r'@intent\("([a-zA-Z]+)"\)')


def fail(msg):
    print(f"FAIL: {msg}")
    return 1


def main():
    # --- 1) 从 loopd.py 提取实现方动词集 -----------------------------------
    if not os.path.isfile(LOOPD_SRC):
        return fail(f"loopd 源码不存在: {LOOPD_SRC}")
    try:
        with open(LOOPD_SRC, encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        return fail(f"读取 loopd.py 失败: {e}")
    # 逐行提取 @intent("verb")，并跳过注释行：源码里可能有"被移除动词"的说明性注释
    # （如 "# ... @intent(\"run\") 已删除 ..."），不能把注释当注册动词，否则会假绿放行。
    impl_verbs = set()
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = INTENT_RE.search(line)
        if m:
            impl_verbs.add(m.group(1))
    if not impl_verbs:
        return fail(f"从 {LOOPD_SRC} 未解析到任何 @intent 注册动词（检测失效，不能放行）")

    # --- 2) 从 prompts/*.md 提取文档声称的动词集 ----------------------------
    if not os.path.isdir(PROMPTS_DIR):
        return fail(f"prompts 目录不存在: {PROMPTS_DIR}")
    md_files = sorted(
        os.path.join(PROMPTS_DIR, n) for n in os.listdir(PROMPTS_DIR)
        if n.endswith(".md")
    )
    if not md_files:
        return fail(f"{PROMPTS_DIR} 下无任何 *.md，无法做真相巡检（检测失效，不能放行）")

    doc_verbs = set()
    for p in md_files:
        try:
            with open(p, encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            return fail(f"读取 {p} 失败: {e}")
        doc_verbs |= set(PROMPT_VERB_RE.findall(content))

    # --- 3) 三方比对：宣称集 ⊆ 实现集 -------------------------------------
    unknown = sorted(doc_verbs - impl_verbs)
    if unknown:
        print(
            "FAIL: prompts 引用了 loopd.py 未注册的动词: "
            + ", ".join(f"loopd {v}" for v in unknown)
        )
        return 1

    print(
        f"OK: {len(doc_verbs)} 个文档动词全部 ∈ loopd 实现的 "
        f"{len(impl_verbs)} 个 @intent 动词（漂移=0）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())