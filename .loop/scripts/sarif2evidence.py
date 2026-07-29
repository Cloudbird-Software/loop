#!/usr/bin/env python3
"""sarif2evidence.py — convert SARIF to unified evidence JSON envelope.
Usage: python sarif2evidence.py <lens-name> <sarif-file>
"""
import json, sys, datetime, pathlib

def main():
    if len(sys.argv) < 3:
        print("Usage: sarif2evidence.py <lens-name> <sarif-file>", file=sys.stderr)
        sys.exit(1)
    lens = sys.argv[1]
    sarif_path = sys.argv[2]
    sarif = json.loads(pathlib.Path(sarif_path).read_text())
    findings = []
    for run in sarif.get("runs", []):
        for result in run.get("results", []):
            loc = result.get("locations", [{}])[0].get("physicalLocation", {})
            findings.append({
                "rule_id": result.get("ruleId", "unknown"),
                "path": loc.get("artifactLocation", {}).get("uri", ""),
                "line": loc.get("region", {}).get("startLine", 0),
                "severity": result.get("level", "note"),
                "message": result.get("message", {}).get("text", ""),
                "raw_ref": f"{sarif_path}#/runs/0/results/{len(findings)}"
            })
    envelope = {
        "lens": lens,
        "shard": "S1",
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "tool": {"name": "sarif-converter", "version": "0.1", "sha256": "TODO"},
        "scope": {"base_sha": "TODO", "head_sha": "TODO", "files": 0},
        "findings": findings
    }
    print(json.dumps(envelope, indent=2))

if __name__ == "__main__":
    main()
