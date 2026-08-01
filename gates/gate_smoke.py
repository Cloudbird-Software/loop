# gates/gate_smoke.py —— 运行 .loop/smoke.sh，据退出码判定（exit 0=pass, 1=fail）
# gate 契约：子进程运行，exit 0=pass，exit 1=fail（与 run_gates.py 对齐）。
# 采纳 Copilot PR review 建议：保留 smoke.sh 的原始退出码向上冒泡，0/1 原样透传，
# 其他退出码（>1，脚本崩溃/用法错误）也原样冒泡，避免丢失 error 分类与排障信号。
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
SMOKE = os.path.join(REPO_ROOT, ".loop", "smoke.sh")

if not os.path.isfile(SMOKE):
    print(f"FAIL: smoke.sh not found at {SMOKE}")
    sys.exit(1)

p = subprocess.run(["bash", SMOKE], cwd=REPO_ROOT)
if p.returncode == 0:
    print("OK: smoke.sh passed")
    sys.exit(0)
# 非 0 退出码原样向上冒泡并区分语义（Copilot review 建议）：
#   returncode==1 → FAIL（smoke 显式断言失败）
#   returncode>1  → ERROR（脚本崩溃/用法错误/信号终止）
# 两者都保留原始退出码向上冒泡，让 run_gates 能据 exit code 分类排障。
if p.returncode == 1:
    print(f"FAIL: smoke.sh exited {p.returncode}")
else:
    print(f"ERROR: smoke.sh exited {p.returncode} (crash/usage error)")
sys.exit(p.returncode)
