# gates/gate_minage.py —— 7 天冷静期
import json, sys, datetime, urllib.request, yaml, subprocess
MIN = yaml.safe_load(open("UPSTREAM.yaml"))["policy"]["min_age_days"]
new = json.loads(subprocess.run(["python","gates/lockdiff.py"],capture_output=True,text=True).stdout)
bad = []
for pkg, ver, published in new:                       # lockdiff 负责查发布时间
    age = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(published)).days
    if age < MIN: bad.append(f"TOO_YOUNG {pkg} {ver} published={published} age={age}d")
if bad and "cooldown-waived" not in sys.argv: print("\n".join(bad)); sys.exit(1)
print("OK")
