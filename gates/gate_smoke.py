# gates/gate_smoke.py —— 运行 .loop/smoke.sh，据退出码判定（exit 0=pass, 1=fail）
# gate 契约：子进程运行，exit 0=pass，exit 1=fail（与 run_gates.py 对齐）。
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
print(f"FAIL: smoke.sh exited {p.returncode}")
sys.exit(1)
