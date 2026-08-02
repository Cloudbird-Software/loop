#!/usr/bin/env python3
"""outbound — 出站过滤：把文本中的敏感凭据脱敏为 `***`。

本模块是"出站数据净化"的唯一权威正则源：
  - SECRET_PATTERNS：检测敏感凭据的正则（GitHub PAT / AWS 访问密钥等）。
  - scrub_outbound()：把匹配到的凭据替换为 `***`。

正则唯一性约束（W1-5）：the conductor/outbound 的脱敏正则必须与本仓 gates/gate_secrets.py
的检测正则用同一来源（SECRET_PATTERNS），避免"gate 能检出但出站只脱了一半"的漏网。

匹配策略：对多目标正则统一用 `(?i)` 或按需，捕获完整凭据串。

用法：
  from conductor.outbound import scrub_outbound, SECRET_PATTERNS
  clean = scrub_outbound("token ghp_ABCD...")
"""
import re

# 敏感凭据正则——检测与脱敏共用（权威唯一源，勿在别处复制正则）。
# 每项 pattern 捕获完整凭据 token，替换时整体打码为 ***。
SECRET_PATTERNS = (
    # GitHub 经典/个人访问令牌 GitHub PAT：ghp_ gho_ ghu_ ghs_ ghr_ + 36 位 base62
    re.compile(r"(?:ghp_|gho_|ghu_|ghs_|ghr_)[a-zA-Z0-9]{36}"),
    # GitHub 细粒度令牌（fine-grained）：github_pat_ + 81 位 base62+下划线
    re.compile(r"github_pat_[a-zA-Z0-9_]{81}"),
    # AWS 访问密钥 ID：AKIA + 16 位大写字母/数字
    re.compile(r"AKIA[0-9A-Z]{16}"),
)

GITHUB_PAT = SECRET_PATTERNS[0]
GITHUB_FINE_GRAINED = SECRET_PATTERNS[1]
AWS_ACCESS_KEY = SECRET_PATTERNS[2]


def scrub_outbound(text):
    """把 text 中所有命中 SECRET_PATTERNS 的凭据替换为 ***，返回脱敏后文本。

    - 不修改非凭据内容，保持其余文本原样。
    - 逐条 pattern 替换（pattern 间互不重叠，顺序无关）。
    """
    if text is None:
        return text
    redacted = text
    for pat in SECRET_PATTERNS:
        redacted = pat.sub("***", redacted)
    return redacted


def find_secrets(text):
    """返回所有命中 SECRET_PATTERNS 的凭据（去重后的乱序集合）。用于门禁检测。"""
    found = set()
    for pat in SECRET_PATTERNS:
        found.update(pat.findall(text))
    return found