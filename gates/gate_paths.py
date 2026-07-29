# gates/gate_paths.py —— 卡片 paths 与实际 diff 的一致性
import json, subprocess, sys, fnmatch, os, re
pr = os.environ["GITHUB_REF"].split("/")[2]
body = subprocess.run(["gh","pr","view",pr,"--json","body","-q",".body"],
                      capture_output=True, text=True).stdout
m = re.search(r"Card:\s*#(\d+)", body)
card = json.loads(subprocess.run(["gh","issue","view",m.group(1),"--json","body","-q",".body"],
                 capture_output=True, text=True).stdout.split("```json loop")[1].split("```")[0])
base = subprocess.run(["git","merge-base","origin/main","HEAD"],capture_output=True,text=True).stdout.strip()
files = subprocess.run(["git","diff","--name-only",base,"HEAD"],capture_output=True,text=True).stdout.split()
bad = [f for f in files
       if any(fnmatch.fnmatch(f,p) for p in card.get("forbid_paths",[]))
       or not any(fnmatch.fnmatch(f,p) for p in card["paths"])]
if bad: print("OUT_OF_LEASE:\n" + "\n".join(bad)); sys.exit(1)
print("OK")
