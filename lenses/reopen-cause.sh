#!/usr/bin/env bash
# reopen-cause.sh — gh query 30-day reopen/revert/hotfix wave end
# Evidence envelope: {"lens":"reopen-cause","shard":"S1","generated_at":"...","tool":{"name":"...","version":"...","sha256":"..."},"scope":{"base_sha":"...","head_sha":"...","files":0},"findings":[]}
set -euo pipefail
# TODO: implement lens logic (W2/W3)
echo '{"lens":"reopen-cause","shard":"S1","generated_at":"'$(date -Iseconds)'","tool":{"name":"TODO","version":"0","sha256":"TODO"},"scope":{"base_sha":"TODO","head_sha":"TODO","files":0},"findings":[]}'
exit 0
