#!/usr/bin/env python3
"""gate_secrets — secrets 门：检测敏感凭据泄漏（W1-5）。

治本：凭据一旦被发现必须 FAIL（exit 1），禁止 fail-open（CHARTER N11）。

检测策略（双路径，gitleaks 不可用亦不松开）：
  1. gitleaks 可用（`which gitleaks` 成功）→ 调用 `gitleaks detect` 扫描。
  2. 内置正则兜底（复用 conductor/outbound.SECRET_PATTERNS）无条件执行，
     保证无论 gitleaks 是否存在都能检出。

任一路径检出一条即 FAIL（exit 1）。

用法（被 run_gates.py 以脚本方式调度，无参数时从 stdin 读）：
  python3 gates/gate_secrets.py <path> [path...]   # 扫文件
  python3 gates/gate_secrets.py                    # 从 stdin 读文本
  printf 'token ghp_...' | python3 gates/gate_secrets.py /dev/stdin
退出码：0 = PASS（未检出凭据），1 = FAIL（检出敏感凭据）。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

# 复用出站过滤的唯一权威正则集，保证检测与脱敏一致性（AC-1/AC-2）。
# conductor 是包（__init__.py 存在），gate_secrets.py 位于 gates/ 下，
# 以脚本方式运行时把仓库根加入 sys.path 以便导入。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conductor.outbound import SECRET_PATTERNS  # noqa: E402


def read_inputs(paths):
    """读取待检文本：有路径则读所有文件；无路径则读 stdin。返回 str。"""
    if paths is None or len(paths) == 0:
        return sys.stdin.read()
    chunks = []
    for p in paths:
        # /dev/stdin 支持
        if os.path.realpath(p) == "/dev/stdin":
            chunks.append(sys.stdin.read())
            continue
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            chunks.append(f.read())
    return "\n".join(chunks)


def gitleaks_available():
    """`which gitleaks` 成功即认为可用。"""
    return shutil.which("gitleaks") is not None


def run_gitleaks(text):
    """用 gitleaks 扫描给定文本。返回 (found: bool, detail: str)。

    found=True 表示 gitleaks 检测出凭据（returncode != 0）。
    注意：即便 gitleaks 路径崩溃/超时，也只标记 found=True（fail-closed，
    绝不放行），外层再用内置正则兜底双重确认。
    """
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(text)
            tmp_path = tmp.name
        cfg = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".gitleaks.toml"
        )
        proc = subprocess.run(
            ["gitleaks", "detect", "--source", tmp_path, "--config", cfg,
             "--no-banner", "--report-format", "json"],
            capture_output=True, text=True, timeout=60,
        )
        found = proc.returncode != 0
        detail = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    except subprocess.TimeoutExpired:
        found, detail = True, "gitleaks TIMEOUT (fail-closed)"
    except FileNotFoundError:
        found, detail = False, "gitleaks missing at run time"
    except Exception as e:  # noqa: BLE001
        found, detail = True, f"gitleaks ERROR (fail-closed): {e}"
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:  # noqa: BLE001
            pass
    return found, detail


def scan_regex(text):
    """内置正则扫描。返回命中列表。"""
    hits = set()
    for pat in SECRET_PATTERNS:
        hits.update(pat.findall(text))
    return sorted(hits)


def main():
    paths = sys.argv[1:]
    text = read_inputs(paths)

    hits = scan_regex(text)  # 无条件执行，兜底随在不在 gitleaks 都保证检出

    use_gitleaks = gitleaks_available()
    gleak_found = False
    if use_gitleaks:
        gleak_found, detail = run_gitleaks(text)
        if gleak_found:
            print(f"FAIL: gitleaks detected secrets\n{detail}")

    if hits:
        print("FAIL: sensitive credentials detected:")
        for h in hits:
            print(f"  - {h}")

    if hits or (use_gitleaks and gleak_found):
        return 1
    if use_gitleaks:
        print("PASS: gitleaks scanned, no secrets")
    print("PASS: no sensitive credentials detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())