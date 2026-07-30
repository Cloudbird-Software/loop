# gates/gate_minage.py —— 7 天冷静期（C-012 最小测试：缺失环境/SKIP 时不崩，exit 0）
import json, sys, datetime, subprocess, os

def _skip(msg):
    print(f"SKIP: {msg}")
    sys.exit(0)

# 1. 找上游：若无 UPSTREAM.yaml 且没 lockdiff，跳过（很多样板 repo 没上游依赖）
UP = None
for p in ["UPSTREAM.yaml", "UPSTREAM.yml", os.path.join(os.path.dirname(__file__), "..", "UPSTREAM.yaml")]:
    if os.path.exists(p):
        UP = p; break
if UP is None:
    _skip("no UPSTREAM.yaml found (not a downstream repo)")

try:
    import yaml
    MIN = yaml.safe_load(open(UP))["policy"]["min_age_days"]
except Exception as e:
    _skip(f"UPSTREAM.yaml no policy.min_age_days or yaml missing ({e})")

# 2. 跑 lockdiff，缺就跳过
try:
    p = subprocess.run(["python3", os.path.join(os.path.dirname(__file__), "lockdiff.py")],
                       capture_output=True, text=True, timeout=60)
    new = json.loads(p.stdout) if p.stdout.strip() else []
except Exception as e:
    _skip(f"lockdiff unavailable ({e})")

bad = []
for item in new:
    if len(item) < 3: continue
    pkg, ver, published = item[0], item[1], item[2]
    if not published: continue
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        pub = datetime.datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=datetime.timezone.utc)
        age = (now - pub.astimezone(datetime.timezone.utc)).days
    except Exception:
        continue
    if age < MIN:
        bad.append(f"TOO_YOUNG {pkg} {ver} published={published} age={age}d")

if bad and "cooldown-waived" not in sys.argv:
    print("\n".join(bad)); sys.exit(1)
print("OK")
