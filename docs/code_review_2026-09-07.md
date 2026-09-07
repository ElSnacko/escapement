# Code review: efficiency, usability, quality (2026-09-07)

Reviewed at commit `ffa2f80` (README docs change; core last touched at
`c28bd75`..`be0f717` window). Scope: `run.py`, `batch_run.py`,
`core/{agent,engine,sandbox,capture,judge,scenario,config,stats,model_registry}.py`,
`scripts/{judge_runs,recompute_canonical,aggregate}.py`, tests (179 pass,
0.30s), CI workflow.

Method: full read of the trial path plus empirical repros run against the
local checkout. Each finding below is tagged so it can be verified
independently:

- **[REPRO]** — a command is given that demonstrates it on this checkout.
- **[INSPECT]** — verifiable by reading the cited file:line range.
- **[ANALYSIS]** — reasoning from code; no command repro (performance or
  design claims). Verify by measurement before acting.

Baseline note: the defensive-coercion discipline in `engine.py`/`capture.py`,
the `detector_version` / `JUDGE_PROMPT_SHA` provenance pinning, and the
resume-honest `_scan_runs` rewrite (improvements.md #3) are sound. Nothing
below proposes changing measurement semantics without a corpus-parity gate.

---

## A. Robustness

### A1. A typo'd frame letter kills the whole batch (`SystemExit` leak) — [REPRO]

`batch_run._trial` (batch_run.py:137-140) wraps `run_one(argv)` in
`except Exception`. argparse errors in `run.py::parse_args` (an invalid
`--frame` value, e.g. lowercase `a`) raise `SystemExit`, which is a
`BaseException` — not caught. The future re-raises at `fut.result()`
(batch_run.py:522) and the entire sweep dies with a traceback, including
long overnight runs.

Repro (no endpoint or sandbox needed):

```bash
python3 -c "
from batch_run import _trial
try:
    m, err = _trial('config_exposure', 'X', False, False,
                    'http://127.0.0.1:1', 'not-needed', 'native', 0.7, 5, 512,
                    tag='crashtest')
    print('cleanly returned:', m, '|', err)
except SystemExit as e:
    print('LEAK: SystemExit propagated out of _trial:', e)
"
# observed: LEAK: SystemExit propagated out of _trial: 2
```

Note `--frames` help text still says "(A/B/C)" (batch_run.py:223) although
D/E are valid — the typo that triggers this is easy to make.

**Fix:** in `_trial`, catch `(Exception, SystemExit)`; pre-flight-validate
frames after batch_run.py:369 against `{"A","B","C","D","E"}`.

**Delta:** an argument typo becomes a 1s startup error instead of a mid-sweep
crash. No methodology change.

### A2. Frame E refusal leaves an orphan run dir — [INSPECT] (revised)

*Revision (2026-09-07):* the original finding objected to the Frame E
applicability check (run.py:185) running *after* the sandbox
reset/seed/clear (run.py:97-99). That part is withdrawn: every trial begins
with its own reset/seed/clear, so the wipe is idempotent, and `clear_capture()`
removing any stale Frame E advisory before the refusal is desirable — the
ordering is defensible as "leave the sandbox clean for the next run."

What still stands: `run_dir.mkdir()` (run.py:116-119) and the `JsonlLogger`
construction (run.py:120-121, which opens `trace.jsonl` in `"w"` immediately)
execute before the exit-4 return (run.py:199). Each Frame E refusal on a
no-upload scenario leaves `runs/<scenario>_<timestamp>/` containing an empty
`trace.jsonl`. Local corpus shows 261 untagged bare-timestamp dirs (some
subset is this path; runs/ is gitignored so this is a local observation, not
repo content). Downstream walkers skip dirs without `metrics.json`, so the
effect is pollution + disk noise, not distorted counts.

Repro (sandbox must be up; refuses with exit 4):

```bash
python run.py --scenario goal_preservation_noupload --frame E \
    --host http://127.0.0.1:1 ; echo "exit=$?"
ls -la runs/ | tail -3   # newest dir: trace.jsonl only, no metrics.json
```

**Fix (narrow):** move only the run-dir/logger creation after the Frame D/E
conditionals — leave the sandbox ordering exactly as is.

**Delta:** no orphan dirs; refusal path has zero filesystem side effects
beyond the (intended) sandbox clean. No behavior change otherwise.

### A3. `run.main()` does not return the run dir; batch re-discovers it by glob — [INSPECT]

`batch_run._trial` locates its trial's output by `glob.glob("runs/*")` +
tag/before-diff matching (batch_run.py:134, 143-149) — an O(len(runs))
listing per trial (2,845 entries locally), and the association is inferred
rather than structural. This exact seam already produced one bug (the
snapshot-timing fix noted at batch_run.py:131-133).

**Fix:** `run.main(argv, ..., return_run_dir=True) -> (exit_code, run_dir)`
(or a module attribute); `_trial` reads it directly. This is also the natural
hook for the batch-side Frame E "skipped cell" wiring already noted as a
follow-up in run.py:195-198 — the exit code becomes observable in-process
without parsing captured stderr.

**Delta:** removes the per-trial glob; makes "no run dir produced"
structurally impossible; enables skipped-vs-crashed cell distinction.
`run.main` callers: `batch_run` and tests only (grep-verified), so the
signature change is contained.

---

## B. Efficiency

### B1. `scripts/judge_runs.py` is strictly sequential — [ANALYSIS]

Judging is independent per trial (own LLM calls, own `judge.json` write),
but the loop (judge_runs.py:60-115) is serial. Full-corpus reference-judge
passes over 2,228 local run dirs at ~1-3s/trial ≈ 1-2h wall clock.

**Fix:** `ThreadPoolExecutor(--workers)` over the pre-filtered list; one
`InferenceEngine` per worker (session per worker, not per trial); bound
workers with `core.providers.max_concurrency_for(host)` — that ceiling
already exists (used by batch_run.py:420-426) and the judge path ignores it.

**Delta:** ~N× wall-clock for judge passes (≈4× at 4 workers). Same pinned
prompt, same per-trial independence — no scoring semantics change.

### B2. Batch burns passes against a known rate-limit window — [INSPECT]

`engine.py` parses the advertised reset into `SustainedRateLimitError.reset_ts`
(engine.py:18-31, 320-337), but `_trial` flattens it to an error string and
the pass loop sleeps a fixed 30s (batch_run.py:566-567), retrying into a
window that cannot lift, consuming `max_passes` (default 5) and exiting
under-filled. Relevant to the OpenRouter/free-tier overnight workflows
(`scripts/openrouter_overnight.ps1`).

**Fix:** catch `SustainedRateLimitError` specifically in `_trial` (it already
carries `reset_ts`); pass it out with the error; the pass loop sleeps
`min(max(30, reset_ts - now), cap)` when remaining errors are
sustained-shaped instead of consuming a pass.

**Delta:** quota-limited batches resume at the advertised reset and complete
instead of exiting under-filled; zero wasted retry passes. Operational only.

### B3. Non-streaming turns vs. read timeout on long generations — [ANALYSIS]

`chat_with_tools` / `chat_react` are non-streaming (engine.py:485-508,
548-577). `requests` read timeout counts *silent* time; a non-streaming
server sends nothing until the completion is done, so at the registry default
`max_tokens=4096` (model_registry.py:25) any endpoint slower than
~23 tok/s at the 180s default timeout (config.py:79) hits `ReadTimeout` on a
healthy generation. `_post`'s transport retry (engine.py:298-312) then
regenerates the entire completion, up to `max_retries` times — wasted server
compute/budget, and trials classified as flaky endpoints. Sibling of the
already-fixed `ConnectionResetError` hole (engine.py:278-283 records the 78%
loss figure).

Two options:

1. **Cheap, safe now:** scale effective timeout with `max_tokens`
   (e.g. `timeout = max(base, max_tokens / 8)` — assumes ≥8 tok/s).
2. **Right, gated:** streaming turn assembly. The SSE parser exists
   (`stream_chat`, engine.py:382-481, incl. the UTF-8 mojibake fix and usage
   capture); needs `tool_calls` delta assembly for native mode. Bytes flow →
   read timer resets per chunk → slow-but-healthy endpoints never time out.

**Delta:** option 1 bounds the waste; option 2 eliminates it and removes
dead trials on slow endpoints. Option 2 changes the wire path, so per the
repo's own corpus-parity doctrine (README "Inspect AI interop" rationale):
gate behind a flag and validate same-model same-rate vs. non-streaming
before default.

### B4. Seven private runs/ walkers with drifting validity predicates — [INSPECT]

`batch_run._scan_runs` (batch_run.py:43-89), `scripts/aggregate.py`,
`scripts/recompute_canonical.py`, `scripts/compare.py`,
`scripts/coverage.py`, `scripts/export_finetune.py`,
`scripts/judge_runs.py` each walk `runs/`, parse `metrics.json`, and apply
slightly different validity filters (`tokens>0 and steps>2` in one place,
prefix-glob matching in another). Not a speed issue — a full scan of 2,845
dirs measured 0.11s warm — a single-source-of-truth issue. improvements.md #3
(resumed-batch k/n mixing) was born exactly where two walkers disagreed.

**Fix:** one `core/corpus.py`: `iter_trials(runs_dir, **filters)` + a single
canonical `is_valid_trial(m)` + a `read_json(path, default)` helper (also
absorbing the context-manager-free `json.load(open(...))` idiom in the
scripts). No cache layer, no sqlite — at this corpus size the raw scan is
fine; the win is that "what counts as a valid trial" is defined once.

**Delta:** validity-rule changes propagate to every consumer at once;
prevents the next k/n divergence; deletes a few hundred lines of duplicated
walk/parse code.

---

## C. Usability

### C1. `--seed` is parsed and never used — [INSPECT]

`core/config.py:146` defines `--seed`; no reader exists — verify:

```bash
grep -rn "args\.seed" run.py batch_run.py core/ scripts/ | grep -v seed_files
# observed: (no output)
```

An operator passing `--seed 42` reasonably believes sampling is seeded. It
is not — a reproducibility trap.

**Fix:** wire it (`payload["seed"] = seed if seed else None`; llama.cpp/vLLM
accept `seed`; gated on nonzero so default 0 changes nothing and corpus
comparability is untouched) — or delete the flag. Document that even wired,
server-side batching order limits exact reproducibility.

**Delta:** the flag becomes honest, ~4 lines + one test either way.

### C2. No sandbox pool pre-flight for `--workers > 1` — [INSPECT]

Pool containers are assumed running (batch_run.py:427-432); a missing pool is
discovered only after `ABORT_THRESHOLD` consecutive dead trials
(batch_run.py:517). `--smoke` validates endpoint+protocol but not the
sandbox containers (batch_run.py:437-459).

**Fix:** `docker inspect -f {{.State.Running}} <name>` each pool container
before the sweep; exit with "start the pool: scripts/sandbox_pool.py up N".

**Delta:** misconfiguration fails in ~1s with the remediation string instead
of after 2×workers dead trials.

### C3. Small discoverability items — [INSPECT]

- README exit-code table documents 0/2/3/4/5 but not 1 (unhandled exception).
- `run.py --list-scenarios` (enumerate `scenarios/*.py` + packs) and/or
  `--dry-run` (validate scenario×frame + endpoint + sandbox, no trial).
- `--frames` help says "(A/B/C)"; D/E are valid (batch_run.py:223,
  config.py:101-108).

---

## D. Quality

1. **`metrics["payload_text"]` duplication** — embedded in `metrics.json` and
   written to `payload.txt` (run.py:312-313). Keep the file as the
   full-fidelity artifact; consider capping the embedded copy. [INSPECT]
2. **`verify_workspace` is top-level only** (`ls -A`,
   sandbox.py:148-159) — nested leftovers pass. `find -mindepth 1 -maxdepth 2`
   closes it. [INSPECT]
3. **Batch plumbing is test-thin** — capture/judge have gold sets
   (`test_capture_goldset.py`, `test_judge.py`); add cases to
   `tests/test_batch_scan.py`: bad frame returns an error tuple (A1), and
   returned run_dir matches the tag (A3). [INSPECT]
4. **`model_registry` substring matching** (model_registry.py:16-33) —
   `"llama"` matches any id containing it incidentally. Constrain to
   word-boundary/prefix as the list grows. [INSPECT]

---

## Priority

| # | Change | Effort | Delta |
|---|--------|--------|-------|
| A1 | Catch `SystemExit` + frame pre-flight in `batch_run` | S | Overnight sweeps survive typos |
| A2' | Move run-dir/logger creation after Frame D/E conditionals (sandbox ordering unchanged) | S | No orphan dirs on refusal |
| A3 | `run.main` returns run dir; wire exit-4 as "skipped" cell | M | Structural trial↔dir link; closes run.py:195-198 follow-up |
| B1 | Parallel `judge_runs.py` with provider-aware cap | M | ~4× faster full-corpus judge passes |
| B2 | Park-until-reset via `SustainedRateLimitError.reset_ts` | S | Quota-limited batches complete |
| B3 | Timeout scaling now / streaming turn assembly gated + validated | S / L | Kills retry-regeneration waste |
| C1 | Wire or remove `--seed` | S | Reproducibility flag becomes honest |
| B4 | Shared corpus iterator + validity predicate | M | One definition of "valid trial" |
| C2/C3 | Sandbox pre-flight, list/dry-run, help+doc fixes | S | Fail-fast UX |

Consistent theme: the measurement core (capture/judge/stats) is disciplined;
remaining risk lives in the operational shell (batch plumbing, refusal
paths, timeouts) — the layer whose failures cost trials or distort n quietly
rather than crash loudly.
