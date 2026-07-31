#!/usr/bin/env bash
# promptfoo/run.sh — entry point for the nightly-rubric job (card R11-7).
#
# Wired into .github/workflows/nightly-rubric.yml by R14-2 (that workflow is owned
# by R14-2; do NOT edit it here). R14-2 should replace the bare
#   promptfoo eval -c promptfoo/promptfooconfig.yaml --filter-metadata rubric=true
# step with a call to this wrapper:
#   bash promptfoo/run.sh
#
# Behavior:
#   - If LLM_GATEWAY_KEY (and PROMPTFOO_API_KEY) is absent → print
#     `SKIPPED_NO_CREDENTIALS` to stderr and exit 77. This is a deliberate,
#     distinguishable nonzero code so nightly-rubric never silently exits 0.
#   - If a key is present → run
#     `promptfoo eval -c <this_dir>/promptfooconfig.yaml --filter-metadata rubric=true`
#     and propagate promptfoo's exit code (via exec).
set -euo pipefail

# Distinguishable "skipped, no credentials" exit code (EX_NOPERM per sysexits).
SKIPPED_NO_CREDENTIALS=77

# Treat an unset key as "no credentials". PROMPTFOO_API_KEY is honored as a
# fallback so local devs without gateway access can still drive promptfoo's
# own providers.
if [ -z "${LLM_GATEWAY_KEY:-}${PROMPTFOO_API_KEY:-}" ]; then
  echo "SKIPPED_NO_CREDENTIALS: LLM_GATEWAY_KEY (or PROMPTFOO_API_KEY) is not set; not running promptfoo eval." >&2
  exit "$SKIPPED_NO_CREDENTIALS"
fi

# The provider config reads the key from LLM_GATEWAY_KEY (apiKeyEnvar) and the
# base URL from the OPENAI_BASE_URL env var (promptfoo's openai provider).
# Map the gateway base URL onto OPENAI_BASE_URL, with a safe default. If a key
# is present but the gateway is unreachable, promptfoo exits nonzero after
# retries (never a silent EXIT=0).
: "${LLM_GATEWAY_BASE_URL:=https://api.openai.com/v1}"
export LLM_GATEWAY_BASE_URL
export OPENAI_BASE_URL="${LLM_GATEWAY_BASE_URL}"

# Resolve the config relative to this script so the wrapper works from any CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$SCRIPT_DIR/promptfooconfig.yaml"

if [ ! -f "$CONFIG" ]; then
  echo "::error::promptfoo config missing at $CONFIG" >&2
  exit 1
fi

# exec so promptfoo's exit code becomes this script's exit code (no masking).
exec promptfoo eval -c "$CONFIG" --filter-metadata rubric=true "$@"
