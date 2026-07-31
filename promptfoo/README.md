# promptfoo/ — LOOP prompt-contract rubric scaffold (card R11-7)

This directory is the **promptfoo** scaffold that grades the LOOP prompt contracts
(`prompts/P-*.md`) every night. It is consumed by
`.github/workflows/nightly-rubric.yml` (the `promptfoo-rubric-nightly` job).

> **Scope boundary**: this scaffold only creates files under `promptfoo/`. The
> nightly workflow `.github/workflows/nightly-rubric.yml` is **owned by R14-2** —
> do **not** edit it from this card. Wiring `run.sh` into the workflow is R14-2's
> job. `UPSTREAM.yaml` registration of the promptfoo version is **R11-3's** job —
> do **not** edit `UPSTREAM.yaml` here.

## Layout

```
promptfoo/
├── promptfooconfig.yaml   # 5 rubric test cases (metadata.rubric: true), provider config
├── run.sh                 # no-credentials → SKIPPED_NO_CREDENTIALS (exit 77); else runs promptfoo
└── README.md              # this file
```

## The 5 rubric cases (R11-7 acceptance (a)-(e))

Each case is tagged `metadata.rubric: true` so
`promptfoo eval --filter-metadata rubric=true` selects exactly these five.

| # | Coverage area | Contract source | Assertions |
|---|---------------|-----------------|------------|
| (a) | 不得输出 PASS/FAIL 只输出 claim | P2 §4-5, P4 first-discovery, P-continue §7 | `not-icontains VERDICT=PASS`, `not-icontains VERDICT=FAIL`, `not-icontains VERDICT`, `llm-rubric` (single falsifiable claim, no verdict) |
| (b) | 必须含 repro | P-continue §7, P4 first-discovery | `regex 复现\|reproduc...`, `regex 环境\|environment\|sandbox\|SHA`, `llm-rubric` (reproduction section) |
| (c) | 必须含 falsifier | P4 §0, P4 blind phase | `regex falsif\|证伪\|disprove\|反例...`, `llm-rubric` (concrete falsifier, not confirmation) |
| (d) | 不得自证 (N12) | P-continue §0 N12, §9.9, P4 §0 | `not-icontains I verified my own`, `not-icontains self-verif`, `llm-rubric` (refuses self-verify, delegates to heterogeneous verify) |
| (e) | 超出 paths 即拒绝 | P0 内容铁律, P-continue §3-4 | `regex refus\|拒绝\|outside\|超出\|forbid...`, `llm-rubric` (refuses out-of-paths edits) |

## How to run locally

Prerequisites: Node.js + the promptfoo CLI (see version below), and an
OpenAI-compatible LLM gateway reachable via `LLM_GATEWAY_BASE_URL` with an API
key in `LLM_GATEWAY_KEY`.

```bash
# 1. Install promptfoo (pin the version registered in UPSTREAM.yaml by R11-3):
npm install -g promptfoo@<VERSION>     # see "Version to register" below

# 2. Set credentials (the wrapper maps LLM_GATEWAY_BASE_URL -> OPENAI_BASE_URL):
export LLM_GATEWAY_KEY=<your-gateway-key>
export LLM_GATEWAY_BASE_URL=https://your-gateway.example/v1
# Model is gpt-4o-mini by default; edit providers[].id in promptfooconfig.yaml
# to point at a different model, or have your gateway route the alias.

# 3a. Run via the wrapper (recommended — same path nightly-rubric should call):
bash promptfoo/run.sh

# 3b. Or run promptfoo directly (mirrors the nightly command):
promptfoo eval -c promptfoo/promptfooconfig.yaml --filter-metadata rubric=true
```

To run a single case during development, drop the filter and use promptfoo's
`--filter-tests` / `--filter-pattern`, or temporarily set `rubric: true` only on
the case you want.

## No-credentials behavior (NEVER silent EXIT=0)

`promptfoo/run.sh` checks for `LLM_GATEWAY_KEY` (or `PROMPTFOO_API_KEY`) **before**
invoking promptfoo:

- **Absent** → prints `SKIPPED_NO_CREDENTIALS: ...` to stderr and **exits 77**
  (a deliberate, distinguishable nonzero code; `EX_NOPERM`). promptfoo is never
  launched, so the eval cannot silently pass with zero assertions run.
- **Present** → runs
  `promptfoo eval -c promptfoo/promptfooconfig.yaml --filter-metadata rubric=true`
  via `exec`, so promptfoo's own exit code is propagated. A real rubric failure
  (an assertion fails) or a provider/network error returns nonzero normally.

Additionally, even without the wrapper the provider config uses
`apiKeyEnvar: LLM_GATEWAY_KEY`, so a bare `promptfoo eval ...` with no key fails
to initialize the provider and exits nonzero — there is no path to a silent
`EXIT=0` on missing credentials.

> The nightly workflow should call `bash promptfoo/run.sh` (R14-2's wiring task)
> rather than the bare `promptfoo eval ...`, so the `SKIPPED_NO_CREDENTIALS`
> signal is produced cleanly.

## How to add a new rubric case

1. Open `promptfoo/promptfooconfig.yaml`.
2. Append a new entry under `tests:`. **Always set `metadata: { rubric: true }`**
   so `--filter-metadata rubric=true` selects it.
3. Provide `vars:` with three fields used by the shared prompt template:
   - `contract` — the relevant excerpt(s) from `prompts/P-*.md` (cite the file + section).
   - `scenario` — a concrete situation the model under test faces.
   - `task` — the exact artifact the model must produce.
4. Add `assert:` entries. Prefer deterministic assertions
   (`icontains`, `not-icontains`, `regex`) for reliability; use `llm-rubric` for
   semantic checks that a substring cannot capture. Combine a positive
   (`icontains`/`regex`) with a negative (`not-icontains`) where appropriate.
5. Validate the YAML:
   ```bash
   python3 -c "import yaml,sys; yaml.safe_load(open('promptfoo/promptfooconfig.yaml')); print('ok')"
   ```
6. Re-run locally: `bash promptfoo/run.sh` (or with `--filter-metadata rubric=true`).

When a case targets a *non*-rubric (e.g. a smoke test you don't want in
nightly), omit `metadata.rubric` so the nightly filter skips it.

## Version to register (handoff to R11-3)

Register in `UPSTREAM.yaml` (R11-3's task — do **not** edit `UPSTREAM.yaml` here):

```
promptfoo: 0.121.19   # npm view promptfoo version ; npm install -g promptfoo@0.121.19
```

If a newer stable is pinned later, update both `UPSTREAM.yaml` (R11-3) and the
install command above; the scaffold itself is version-agnostic.

## Wiring (handoff to R14-2)

The existing nightly step is:

```yaml
promptfoo eval -c promptfoo/promptfooconfig.yaml --filter-metadata rubric=true
```

R14-2 should replace it (or wrap it) with:

```yaml
bash promptfoo/run.sh
```

so the `SKIPPED_NO_CREDENTIALS` (exit 77) path is produced instead of a raw
provider-init error when `LLM_GATEWAY_KEY` is missing. The wrapper still runs the
exact same `promptfoo eval -c promptfoo/promptfooconfig.yaml --filter-metadata rubric=true`
command when a key is present.
