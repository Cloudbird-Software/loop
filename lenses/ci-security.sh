#!/usr/bin/env bash
set -euo pipefail
zizmor --persona pedantic --format sarif . > .loop/audit/ci-security.sarif || true
python .loop/scripts/sarif2evidence.py ci-security .loop/audit/ci-security.sarif
