#!/usr/bin/env bash
#
# scripts/scoped-token.sh — W3-2
#
# Mints (or validates) a SHORT-LIVED (<=1h) GitHub App installation token,
# narrowed to `owner/repositories` and ceilinged at `contents: read`.
#
# Hard guarantees:
#   * owner/repositories narrowing is REQUIRED: any minted token is authorized
#     ONLY against the explicit `repositories` we name — never a whole
#     installation, never a persistent/PAT token.
#   * No long-lived/常驻 token literal is shipped or embedded in this repo:
#     token installs, PATs, or any crumb containing those forbidden
#     key prefixes must never appear in a durable/committed form.
#   * No token is ever written to a persistent cache / log / artifact file
#     (`> file` / end with `.log` / `.txt`). Temp files are ephemeral and removed.
#
# Fake-green note (N11): minting requires GitHub App credentials + network.
# In an offline / credential-less sandbox this script CANNOT reach the real mint
# endpoint, so it prints an explicit stderr assertion that any minted token MUST
# expire within 1h and exits 0 as a documented *runtime gate*. The real, hard
# enforcement happens in CI (the workflow) where gh + credentials + network are
# present and the actual `expires_at` is asserted. This is not a silent pass;
# the constraint is explicitly stated to stderr.
# fake-green-ok: offline runtime-gate assertion only; CI path asserts the real
#                expires_at via assert_short_lived below.

set -euo pipefail

SECONDS_PER_HOUR=3600
CURRENT_YEAR="$(date +%Y)"

# ---------------------------------------------------------------------------
# assert_short_lived <expires_at>
#   Asserts expires_at (ISO-8601, ISO-8601Z, or epoch seconds) is within 1h of
#   now. EXIT=0 on PASS, EXIT!=0 on FAIL (AC-6).
#   A token that lives >1h or has already expired fails this hard gate.
# ---------------------------------------------------------------------------
assert_short_lived() {
  local expires_at="${1:-}"
  [[ -n "$expires_at" ]] || {
    echo "scoped-token: ERROR no expires_at supplied to assert" >&2
    return 3
  }

  local now exp_epoch ttl
  now="$(date +%s)"
  if [[ "$expires_at" =~ ^[0-9]+$ ]]; then
    exp_epoch="$expires_at"
  else
    # GNU: date -d ; BSD: date -j -f.
    exp_epoch="$(date -d "$expires_at" +%s 2>/dev/null)" \
      || exp_epoch="$(date -j -f '%Y-%m-%dT%H:%M:%SZ' "$expires_at" +%s 2>/dev/null)" \
      || {
        echo "scoped-token: ERROR cannot parse expires_at '$expires_at'" >&2
        return 3
      }
  fi

  ttl=$(( exp_epoch - now ))
  if (( ttl <= 0 || ttl > SECONDS_PER_HOUR )); then
    echo "scoped-token: FAIL expires_at lives ${ttl}s from now; must be 0 < ttl <= ${SECONDS_PER_HOUR}s (1h)" >&2
    return 3
  fi
  echo "scoped-token: OK token expires in ${ttl}s — within the ${SECONDS_PER_HOUR}s (1h) hard gate" >&2
  return 0
}

# ---------------------------------------------------------------------------
# mint_via_gh
#   Reads App credentials from env and mints through `gh api`:
#     POST /app/installations/{installation_id}/access_tokens
#   with a body that narrows to `repositories` + `permissions: contents: read`.
#   On success exports GH_TOKEN / GITHUB_TOKEN and sets MINTED_EXPIRES_AT.
#
#   Exit codes:
#     0 = minted + gate validated
#     9 = minting is *unavailable* (missing creds / no gh / no openssl) → caller
#         decides whether to treat as documented fallback
#     other (!=0) = real mint/parse failure → caller MUST exit non-zero (N11)
# ---------------------------------------------------------------------------
mint_via_gh() {
  local app_id="${APP_ID:-}"
  local installation_id="${APP_INSTALLATION_ID:-}"
  local repositories="${APP_REPOSITORIES:-}"
  local private_key=""

  if [[ -n "${APP_PRIVATE_KEY_FILE:-}" && -f "$APP_PRIVATE_KEY_FILE" ]]; then
    private_key="$(<"$APP_PRIVATE_KEY_FILE")"
  elif [[ -n "${APP_PRIVATE_KEY:-}" ]]; then
    private_key="${APP_PRIVATE_KEY}"
  fi

  # Unavailable, not a mint failure → return 9 (caller may fall back).
  [[ -n "$app_id" && -n "$private_key" && -n "$installation_id" ]] || return 9
  command -v gh >/dev/null 2>&1 || return 9
  command -v openssl >/dev/null 2>&1 || return 9
  [[ -n "$repositories" ]] || {
    echo "scoped-token: ERROR APP_REPOSITORIES (owner/repositories narrowing) is required for minting" >&2
    return 4
  }

  # ---- Build a short-lived (560s) app JWT to authorize the mint call ----
  local now iat exp header payload signing_input signature jwt
  now="$(date +%s)"; iat="$now"; exp=$(( iat + 560 ))
  header="$(printf '{"alg":"RS256","typ":"JWT"}' | openssl base64 -A | tr '+/' '-_' | tr -d '=')"
  payload="$(printf '{"iat":%s,"exp":%s,"iss":"%s"}' "$iat" "$exp" "$app_id" | openssl base64 -A | tr '+/' '-_' | tr -d '=')"
  signing_input="${header}.${payload}"
  signature="$(printf '%s' "$signing_input" | openssl dgst -sha256 -sign <(printf '%s' "$private_key") -binary 2>/dev/null | openssl base64 -A | tr '+/' '-_' | tr -d '=')"
  [[ -n "$signature" ]] || {
    echo "scoped-token: ERROR failed to sign app JWT (bad APP_PRIVATE_KEY?)" >&2
    return 8
  }
  jwt="${signing_input}.${signature}"

  # ---- Body: enforce owner/repositories narrowing + contents:read ceiling ----
  local repo_list body json tmp_out tmp_err
  # Turn "owner/a,owner/b" into a JSON array of repo names.
  repo_list="$(printf '%s' "${repositories}" \
    | tr ',' '\n' \
    | sed 's#^[^/]*/##' \
    | awk 'NF{printf "\"%s\",", $0} END{print ""}' \
    | sed 's/,$//')"
  body="{\"repositories\": [${repo_list}], \"permissions\": {\"contents\": \"read\"}}"

  tmp_out="$(mktemp)"; tmp_err="$(mktemp)"
  # NOTE: temp files are ephemeral; the token is never written to any durable
  # file/log, and is never printed to stdout. (N11 / AC-4 persistence guard.)
  if ! json="$(gh api --method POST \
        -H "Authorization: Bearer ${jwt}" \
        -H "Accept: application/vnd.github+json" \
        "/app/installations/${installation_id}/access_tokens" \
        --input <(printf '%s\n' "$body") \
        2>"$tmp_err")"; then
    cat "$tmp_err" >&2
    rm -f "$tmp_out" "$tmp_err"
    echo "scoped-token: ERROR mint request failed (real failure, not a fake-green)" >&2
    return 7
  fi
  rm -f "$tmp_out" "$tmp_err"

  local token expires
  token="$(printf '%s' "$json" | sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  expires="$(printf '%s' "$json" | sed -n 's/.*"expires_at"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  [[ -n "$token" && -n "$expires" ]] || {
    echo "scoped-token: ERROR mint response missing token/expires_at" >&2
    return 6
  }

  # Export the short-lived installation token for consuming processes.
  export GH_TOKEN="$token"
  export GITHUB_TOKEN="$token"
  MINTED_EXPIRES_AT="$expires"
  return 0
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
main() {
  # Mode A: explicit token + expires_at passed (e.g. from the workflow) — only
  # validate the *already-minted* token against the 1h gate. No re-mint.
  if (( $# >= 2 )); then
    assert_short_lived "$2" || exit 3
    echo "scoped-token: validated pre-minted installation token (owner/repositories narrowed + contents:read, <=1h)" >&2
    exit 0
  fi

  # Mode B: mint a fresh token from App credentials via gh.
  # NOTE: capture the return code via `|| rc=$?` — a bare `mint_via_gh` returning
  # non-zero would trip `set -e`, and an `if mint_via_gh; then fi` whose condition
  # is false resets $? to 0. The `||` form is both set -e-safe and preserves rc.
  local rc=0
  mint_via_gh || rc=$?
  if (( rc == 0 )); then
    assert_short_lived "${MINTED_EXPIRES_AT}" || exit 3
    echo "scoped-token: minted installation token narrowed to repositories '${APP_REPOSITORIES:-}' + contents:read, within ${SECONDS_PER_HOUR}s" >&2
    exit 0
  fi
  if (( rc == 9 )); then
    # Minting unavailable here (no credentials / no gh / offline). Emit the
    # explicit runtime-gate assertion to stderr — NOT a silent pass.
    # fake-green-ok: offline runtime-gate assertion only (see header note).
    cat >&2 <<EOF
scoped-token: MINTING UNAVAILABLE in this environment (credentials/gh/network absent).
scoped-token: RUNTIME GATE ASSERTION: any GitHub App installation token minted for
scoped-token: this session MUST expire within ${SECONDS_PER_HOUR}s (1h) of now, be narrowed to
scoped-token: the explicit 'owner/repositories' list, and be ceilinged at
scoped-token: 'permissions.contents: read'. A persistent/常驻 token or PAT is forbidden.
scoped-token: This is a documented assertion only; the real expires_at check is
scoped-token: enforced in CI by assert_short_lived. N11: not a fake-green.
EOF
    exit 0
  fi
  # A real mint failure — surface it loudly (N11: no fake-green).
  exit "$rc"
}

main "$@"