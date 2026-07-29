#!/usr/bin/env bash
# error-path.sh — Semgrep custom rules daily sharded
# Evidence envelope: {"lens":"error-path","shard":"S1","generated_at":"...","tool":{"name":"...","version":"...","sha256":"..."},"scope":{"base_sha":"...","head_sha":"...","files":0},"findings":[]}
set -euo pipefail
# TODO: implement lens logic (W2/W3)
echo '{"lens":"error-path","shard":"S1","generated_at":"'$(date -Iseconds)'","tool":{"name":"TODO","version":"0","sha256":"TODO"},"scope":{"base_sha":"TODO","head_sha":"TODO","files":0},"findings":[]}'
exit 0
