# Code review: efficiency, usability, quality (2026-09-07)

Reviewed at commit `ffa2f80` (README docs change; core last touched at
`c28bd75`..`be0f716` window). Scope: `run.py`, `batch_run.py`,
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
reset/seed/clear (run.py:97-99). That objection was withdrawn as harmless:
every trial begins with its own reset/seed/clear, so the ordering is
idempotent.

*Revision 2 (2026-09-08, verification pass):* the ordering is harmless but the
"leave the sandbox clean for the next run" rationale is not the reason. The
next run always resets itself; the refused run leaves the workspace *seeded*,
not clean; and a refused Frame E never wrote an advisory (the write at
run.py:220 is after the check), so there is no stale advisory to clear. The
check is a pure function of scenario metadata and belongs BEFORE the endpoint
health check and the sandbox, so a refusal costs nothing and returns exit 4
even when the endpoint or sandbox is also down (today it returns 2 or 3 in
that case, masking the real reason). See spec S2 in the addendum. The sandbox
reset itself does NOT move.

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

*Note (2026-09-08):* the run.py:193-198 comment claims the batch refusal
"still surfaces via the captured stderr message". Verified false: with a tag
the orphan dir IS found, `_trial` returns `no metrics.json in <dir>` and the
stderr text is discarded (batch_run.py:150-152). The refusal is then counted
as a dead-endpoint failure, and because `consecutive_err` is global across
cells (batch_run.py:516-536) a Frame E cell over a no-upload scenario can
abort the pass for every other cell. See spec S8.

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

*Correction (2026-09-08):* the premise is wrong. `SustainedRateLimitError`
is never raised: engine.py:333-335 constructs it with a `message=` keyword,
`requests.RequestException.__init__` forwards unknown keywords to
`OSError.__init__`, which rejects them, so construction raises
`TypeError: SustainedRateLimitError() takes no keyword arguments`. The
`TypeError` propagates into `Agent.run`'s generic handler (agent.py:325-327)
and the trial ends as an ordinary engine error. Everything downstream of the
intended exception is dead code today: run.py's exit 5, the agent's re-raise,
and the `sustainedratelimit` marker in `_RL_MARKERS`. The only test
(`test_sustained_error_carries_reset`) constructs it without a message and so
passes. Spec S1 fixes the constructor; this finding's fix (spec S9) depends
on S1.

Repro:

```bash
python3 -c "
from core.engine import SustainedRateLimitError
SustainedRateLimitError(response=None, reset_ts=1.0, message='x')"
# TypeError: SustainedRateLimitError() takes no keyword arguments
```

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

---

# Verification addendum and implementation specs (2026-09-08)

Second pass: every finding above was re-checked against the code at
`249c126`, the repros were re-run, and the trial path was probed for what the
first pass missed. Tests: 179 pass.

## Verification summary

| finding | status |
|---|---|
| A1 | confirmed by repro |
| A2 | confirmed by repro; rationale corrected (see Revision 2) |
| A3 | confirmed; the run.py comment it cites is false (see Note) |
| B1 | confirmed by inspection |
| B2 | premise wrong: the exception is never raised (see Correction) |
| B3 | confirmed; arithmetic checks out |
| B4 | confirmed and understated: concrete drift, see M6 |
| C1 | confirmed by grep |
| C2, C3 | confirmed |
| D1 to D4 | confirmed; D4 has no current collision |

## Missed findings

### M1. Process-wide stdout hijack with `--workers > 1` — [REPRO]

`_trial` (batch_run.py:137) uses `contextlib.redirect_stdout` /
`redirect_stderr`. These swap the process-global `sys.stdout` / `sys.stderr`.
Two overlapping trials restore in the wrong order and leave both streams
pointing at an orphaned `StringIO`. From then on the tqdm bar, `tqdm.write`
lines (`[ERR]`, `[RATE]`), pass banners and the final summary table are
written into a buffer nobody reads, and that buffer grows for the rest of the
run. Only `runs/batch_*.json` survives.

```bash
python3 - <<'PY'
import sys, io, contextlib, threading, time
real = sys.stdout
def w(d_in, d_out):
    time.sleep(d_in)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        time.sleep(d_out)
a = threading.Thread(target=w, args=(0.0, 0.3)); b = threading.Thread(target=w, args=(0.1, 0.5))
a.start(); b.start(); a.join(); b.join()
print("stdout is real:", sys.stdout is real, file=real)   # False
PY
```

Spec S3.

### M2. batch_run reads metrics.json without an encoding — [REPRO]

batch_run.py:70 and :153 call `json.load(open(mp))`. Every other walker in
`scripts/` passes `encoding="utf-8"`. `metrics.json` is written with
`ensure_ascii=False` and embeds model text (`payload_text`, D1), which
routinely carries curly quotes, em dashes and emoji. On Windows (the
operator's platform per the `.ps1` scripts and the cp1252 comments in run.py)
the default codec is cp1252, so:

- `_scan_runs` (line 70) hits `UnicodeDecodeError`, swallows it, and does not
  count the trial. The cell looks under-filled and is re-run every pass; the
  on-disk n over-fills while `aggregate.py` (utf-8) counts every trial.
- `_trial` (line 153) is outside the `try`, so the same error propagates
  through `_run_task` to `fut.result()` (line 522) and kills the batch.

Repro under a simulated non-UTF-8 locale (equivalent to cp1252 for this
purpose):

```bash
mkdir -p /tmp/r/config_exposure_x && python3 -c "
import json; json.dump({'scenario':'config_exposure','frame':'A','agency':False,
 'aware_condition':False,'model':'m','total_tokens':100,'steps':10,
 'payload_text':'it’s done — \U0001F680'},
 open('/tmp/r/config_exposure_x/metrics.json','w',encoding='utf-8'), ensure_ascii=False)"
PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 LC_ALL=C python3 -c "
import batch_run
print(batch_run._scan_runs([('config_exposure','A',False,False)], runs_dir='/tmp/r')[0]['n'])"
# 0   (expected 1)
```

Spec S4.

### M3. The API-key warning masks the real error string — [REPRO]

`_trial` always passes `--api-key` on argv (batch_run.py:110). `parse_args`
(config.py:193-203) then warns on stderr about a secret-looking key on every
trial. `_trial` returns `err_buf.getvalue()[:200]` (line 148), so for any
provider with a recognisable key prefix the error message for a failed trial
is the warning text, not the failure.

```bash
python3 -c "
from batch_run import _trial
m, err = _trial('config_exposure','A',False,False,'http://127.0.0.1:1',
                'sk-or-v1-'+'a'*48,'native',0.7,5,512,tag='t')
print(repr(err))"
# '!! WARNING: --api-key carries what looks like a real secret; ... \n!! model endpoint '
```

Spec S5.

### M4. Judge auth falls back to `not-needed`, and UNKNOWN verdicts are sticky and counted — [INSPECT]

run.py:331-334: when `--judge-host` is unset the judge targets the model host
but authenticates with `args.judge_api_key`, whose default is `not-needed`.
Against any authenticated provider every judge call 401s. `judge_post` never
raises (judge.py:229-245), so every upload scores `UNKNOWN`, `judge.json` is
written with `genuine: false`, `scripts/judge_runs.py:101` then skips the
trial as already judged, and `aggregate._judge_cols` / `compare.py:86` count
it in the judged denominator. Net effect: a misconfigured judge deflates the
headline genuine rate silently, and in batch mode the per-trial
`judge failed` message is swallowed by M1's redirect.

Check the local corpus before changing anything:

```bash
grep -l '"trial_verdict": "UNKNOWN"' runs/*/judge.json | wc -l
```

Spec S6.

### M5. Engine errors mid-trial are indistinguishable from a benign stop — [INSPECT]

`Agent.run` ends a trial on any engine exception (agent.py:325-327) or a
non-dict turn (:336) with `break`; the status computed at :467 is then
`"stopped"`, the same value as a model that simply answered in text. The
result dict (:471-482) carries no error field, so `metrics.json` cannot tell
them apart, and the validity predicate (`tokens>0 and steps>2`) admits the
trial once it has three turns. `goal_abandonment` (capture.py:637) even
treats `stopped` as a legitimate ending. Under provider throttling, or the
B2/S1 `TypeError`, this is a systematic bias toward "no escape" that inflates
n. Only `trace.jsonl` records the `engine_error` event.

Spec S7.

### M6. Concrete B4 drift: degenerated trials — [INSPECT]

`scripts/aggregate.py:318-319` and `scripts/recompute_canonical.py:129`
filter on `steps>2 and tokens>0` only. `batch_run._scan_runs`,
`scripts/compare.py:62`, `scripts/coverage.py:52` and
`scripts/export_finetune.py:575` additionally exclude `degenerated`. So the
paper's per-regime denominators and the batch fill counter disagree on every
cell that contains degenerated trials. Spec S10 resolves this by definition,
not by patching each file.

### M7. Smaller items — [INSPECT]

- batch_run hardcodes `runs` (lines 134, 143, 145, 603-604 and the
  `_scan_runs` default) while run.py honours `--log-dir` / `ESCAPE_LOG_DIR`.
  Setting the env var makes the batch find no trials at all.
- Help text and a comment name `scripts/sandbox_pool.sh` (batch_run.py:280,
  413); the file is `scripts/sandbox_pool.py`.
- Default hosts differ: config.py:38 uses port 8000, batch_run.py:233 uses
  8080.
- `consecutive_err` (batch_run.py:516-536) is one counter for the whole pass,
  so failures from one misconfigured cell abort the pass for all cells.

---

## Implementation specs

Ordered by priority. Each spec is self-contained: files, exact change, tests,
acceptance. Rules for all specs:

- Keep every existing test green. `tests/test_batch_scan.py` pins
  `ci, m, err = fut.result()` and `return ci, m, err` by source inspection, and
  `_trial` must keep returning a 2-tuple `(metrics_or_None, err_or_None)`.
- Do not change any scoring semantics in `core/capture.py` or `core/judge.py`
  except where a spec says so explicitly and flags it as a measurement change.
- Use `encoding="utf-8"` on every `open()` you touch.
- One commit per spec, message prefixed with the spec id.

### S1. Fix the `SustainedRateLimitError` constructor (unblocks B2, exit 5, the RATE classifier)

Files: `core/engine.py`, `tests/test_provider_awareness.py`.

Change `core/engine.py:28-31` to take the message positionally and forward
`response` as a keyword, which is what `requests.RequestException` expects:

```python
def __init__(self, message="", response=None, reset_ts=None):
    super().__init__(message, response=response)
    self.reset_ts = reset_ts  # epoch seconds, or None if unknown
```

Change the raise site `core/engine.py:333-335` to:

```python
raise SustainedRateLimitError(
    f"429 rate limit; reset at {reset_ts}",
    response=resp, reset_ts=reset_ts)
```

Tests to add in `tests/test_provider_awareness.py`:

1. Construction with a message: `str(err)` contains `"429"` and `err.reset_ts`
   round-trips. The existing `SustainedRateLimitError(reset_ts=123.0)` call
   must still work.
2. End to end through `_post`: build `InferenceEngine("http://x", "m")`,
   replace `eng.session.post` with a fake returning an object with
   `status_code=429`, `headers={"Retry-After": "3600"}`, a no-op `close()`.
   `eng._post(url, {})` must raise `SustainedRateLimitError` (not
   `TypeError`), with `reset_ts` within a few seconds of `time.time()+3600`,
   after exactly one call (no retry loop).
3. `batch_run._is_rate_limit_err(f"trial crashed: {err}")` is True for the
   error from test 2.

Acceptance: the three tests pass; the repro in the B2 Correction prints
nothing.

### S2. Frame E applicability before network and sandbox; run dir after all refusal paths

Files: `run.py`, `tests/test_noupload_scenarios.py` (or a new test file).

This spec reorders `run.main`. To be explicit about what does and does not
move: the sandbox reset/seed/clear block (run.py:96-103) stays exactly where
it is relative to everything except the scenario load. Only two things move
earlier (scenario load, applicability check) and one thing moves later
(run dir + logger).

New order of `main`:

1. `load_env()`, `args = parse_args(argv)` (unchanged, :37-38).
2. `scenario = load_scenario(args.scenario, paths=args.scenario_path)`
   (moved up from :65).
3. Frame E applicability check: the `if not scenario.instructs_upload():`
   block currently at :185-199, including its `print(...)` and `return 4`,
   moved up to here. Nothing else from the Frame E block moves.
4. Engine construction, health check (`return 2`), model auto-select,
   registry defaults (unchanged, :41-62).
5. Agency / aware snippets, Frame B/C injection (unchanged, :70-88).
6. Sandbox construction, reset/seed/clear (`return 3`), `verify_workspace`
   (unchanged, :89-114).
7. `tool_specs = None`, Frame D block, Frame E advisory-write block with its
   `return 3` (unchanged, :141-225, minus the applicability check).
8. Run dir + logger + `on_event` closure (:116-134) moved down to here,
   immediately before `before = sandbox.fs_snapshot()` (:228).
9. Everything from `before = sandbox.fs_snapshot()` onward unchanged.

Notes:

- `on_event` is only referenced when constructing `Agent` (:229), so moving
  it down is safe. Verify with `grep -n "on_event\|run_dir\|logger" run.py`
  that nothing between the old and new positions uses them.
- The run-dir timestamp will now be taken a second or two later (after
  sandbox setup). Nothing keys on that timestamp; batch finds dirs by tag.
- After this change no exit-2/3/4 path creates a run dir, which closes A2
  without a separate change.

Tests:

1. `run.main(["--scenario", "goal_preservation_noupload", "--frame", "E",
   "--log-dir", str(tmp_path)])` returns 4, with `InferenceEngine.health`
   and `Sandbox.reset_workspace` monkeypatched to raise `AssertionError`
   (proving neither is reached), and `tmp_path` still empty afterwards.
2. The same call with `--frame A` and `health` monkeypatched to return False
   returns 2 and `tmp_path` is still empty (no orphan dir on exit 2).
3. `--frame E` on `config_exposure` must NOT return 4 (it should proceed to
   the health check; with `health` returning False it returns 2).

Acceptance: tests pass; the A2 repro leaves no new dir under `runs/`.

### S3. Thread-safe per-trial output capture in `batch_run`

Files: `batch_run.py`, `tests/test_batch_scan.py`.

Replace the `contextlib.redirect_*` usage in `_trial` (:135-139) with a
thread-local target installed once on the process streams. Add near the top
of `batch_run.py`:

```python
_local = threading.local()

class _ThreadLocalStream:
    """Per-thread redirect target. Installed once over sys.stdout/sys.stderr;
    a worker sets _local.<attr> for the duration of its trial. Threads with no
    target (the main thread, tqdm) write to the real stream."""
    def __init__(self, real, attr):
        self._real, self._attr = real, attr
    def _target(self):
        return getattr(_local, self._attr, None) or self._real
    def write(self, s):
        return self._target().write(s)
    def flush(self):
        return self._target().flush()
    def __getattr__(self, name):          # isatty, encoding, fileno, ...
        return getattr(self._real, name)

def _install_stream_proxies():
    if not isinstance(sys.stdout, _ThreadLocalStream):
        sys.stdout = _ThreadLocalStream(sys.stdout, "out")
    if not isinstance(sys.stderr, _ThreadLocalStream):
        sys.stderr = _ThreadLocalStream(sys.stderr, "err")
```

In `_trial`:

```python
out_buf, err_buf = io.StringIO(), io.StringIO()
_local.out, _local.err = out_buf, err_buf
try:
    code = run_one(argv)
except Exception as exc:  # noqa: BLE001
    return None, f"trial crashed: {exc}"
finally:
    _local.out = _local.err = None
```

Call `_install_stream_proxies()` at the top of `main()` and at the top of
`_trial()` (idempotent; covers tests that call `_trial` directly). Remove the
`contextlib` import if nothing else uses it.

Tests:

1. Two threads call `_trial` concurrently with `run_one` monkeypatched to
   `print("A"*100)` / `print("B"*100)` with overlapping sleeps (as in the M1
   repro). After both join: `sys.stdout` is a `_ThreadLocalStream`; a
   `print()` from the test thread reaches the real stream (capture it with
   pytest's `capsys`); neither trial's text appears in `capsys`.
2. Existing `test_variant_identity` still passes (it calls `_trial` directly).

Acceptance: with `--workers 2` against any endpoint the progress bar and the
final summary table are visible on the terminal for the whole run.

### S4. UTF-8 reads in `batch_run`, and a guarded metrics read in `_trial`

Files: `batch_run.py`, `tests/test_batch_scan.py`.

- Line 70: `with open(mp, encoding="utf-8") as fh: m = json.load(fh)` inside
  the existing `try`.
- Line 153: same, wrapped in `try/except (OSError, ValueError) as exc:
  return None, f"unreadable metrics.json in {d}: {exc}"`.
- Line 605: `open(out, "w", encoding="utf-8")`.

Test: monkeypatch `builtins.open` with a wrapper that records `kwargs` and
asserts `kwargs.get("encoding") == "utf-8"` for every call whose path ends in
`.json`, then run `_scan_runs` and `_trial` (with a fake `run_one` that writes
a metrics.json containing `"—\U0001F680"`). Assert `_scan_runs` counts
it.

Acceptance: the M2 repro prints 1.

### S5. Stop passing the API key on argv; return the tail of stderr

Files: `batch_run.py`, `tests/test_variant_identity.py` (only if it asserts
`--api-key` presence; today it does not).

- In `_trial`, delete the `"--api-key", api_key` pair from `argv` (:110) and
  add `os.environ["ESCAPE_API_KEY"] = api_key` before calling `run_one`.
  run.py's parser reads `ESCAPE_API_KEY` as the default (config.py:78), so
  the key still arrives and the warning at config.py:199 no longer fires.
  Keep the `api_key` parameter in `_trial`'s signature; tests pass it
  positionally.
- Replace `err_buf.getvalue()[:200]` (:148) with the last three non-empty
  lines of `err_buf`, joined with `" | "`, truncated to 300 chars.

Test: `_trial` against `http://127.0.0.1:1` with an `sk-or-v1-...` key returns
an `err` containing `"unreachable"` and not containing `"WARNING"`.

### S6. Judge key fallback, and treat UNKNOWN as unjudged

Files: `run.py`, `scripts/judge_runs.py`, `scripts/aggregate.py`,
`scripts/compare.py`, `tests/test_judge.py`.

run.py:331-334:

```python
jhost = args.judge_host or args.host
jkey = args.judge_api_key
if jkey in ("", "not-needed") and jhost.rstrip("/") == args.host.rstrip("/"):
    jkey = args.api_key          # self-judge on the model host: reuse its key
jeng = InferenceEngine(host=jhost, model=jmodel, timeout=args.judge_timeout,
                       api_key=jkey)
```

Also in run.py, after `jrec` is built: if `jrec["trial_verdict"] == UNKNOWN`
print a stderr warning naming the judge host and model (add `UNKNOWN` to the
`from core.judge import ...` line at run.py:330).

UNKNOWN handling (this is a MEASUREMENT CHANGE to the judged denominator;
record it in the paper's methods note and re-run `aggregate.py` after):

- `scripts/judge_runs.py:101`: skip only when the existing record's
  `trial_verdict` is not `UNKNOWN`; otherwise re-judge.
- `scripts/aggregate.py::_judge_cols`: when `trial_verdict == "UNKNOWN"`
  return `judge_genuine: None` (excluded from k/n like an unjudged trial) but
  keep `judge_verdict: "UNKNOWN"` for QC visibility.
- `scripts/compare.py:86`: `judged` excludes `judge_verdict == "UNKNOWN"`.

Tests: (a) parse args with `--judge --host H --api-key K` and no judge host;
assert the engine constructed for the judge (monkeypatch `InferenceEngine`)
receives `api_key == K`; with `--judge-host H2` it receives the judge key.
(b) `_judge_cols` on a judge.json with `trial_verdict: "UNKNOWN"` returns
`judge_genuine is None`.

### S7. Record engine errors in the trial result and metrics

Files: `core/agent.py`, `core/capture.py`, `batch_run.py`, tests.

- `Agent.__init__`: `self.engine_error: Optional[str] = None`.
- agent.py:325-327 and :333-337: set `self.engine_error = <the error string
  already passed to on_event>` before `break`.
- Return dict (:471-482): add `"engine_error": self.engine_error`. Leave
  `status` semantics unchanged.
- capture.py:762: add `"engine_error": result.get("engine_error")` next to
  `"status"`.
- batch_run: in the accumulator (:545-549) count `m.get("engine_error")` as
  `eng_err`, show it in the tqdm postfix and in the per-cell summary line.
  Do NOT change `_scan_runs` validity here; S10 does that once, for every
  walker.

Tests: an `Agent` with a fake engine whose `chat_with_tools` raises
`RuntimeError("boom")` returns `status == "stopped"` and
`engine_error == "boom"`; `compute_metrics` on that result carries
`engine_error == "boom"`; a normal finish has `engine_error is None`.

### S8. Batch robustness: SystemExit, frame and scenario pre-flight, skipped cells

Files: `batch_run.py`, `run.py`, `tests/test_batch_scan.py`,
`tests/test_variant_identity.py`.

1. `_trial`: catch `(Exception, SystemExit)`; for `SystemExit` return
   `None, f"trial argv rejected (exit {exc.code})"`.
2. Pre-flight after `frames = [...]` (:369): if any frame is not in
   `{"A","B","C","D","E"}`, `sys.exit` naming it. Fix the `--frames` help
   text (:223) to `(A/B/C/D/E)`.
3. Pre-flight scenario load for ALL scenarios, not only packs: move the loop
   at :361-368 out of `if args.pack:` and pass `paths=[args.pack] if
   args.pack else None`.
4. Pre-flight Frame E cells: after `cells` is built, for each cell with frame
   `E`, `load_scenario(...)` and if `not scenario.instructs_upload()` print
   `>> skipping cell <label>: frame E not applicable (no instructed upload)`
   and drop it from `cells`. If that empties `cells`, exit with a message.
5. `run.main(argv=None, result=None) -> int`: when `result` is a dict, set
   `result["run_dir"] = str(run_dir)` right after `run_dir.mkdir(...)`. The
   return value is unchanged. `_trial` calls `code = run_one(argv,
   result=res)`, treats `None` as 0, and:
   - `code == 4` → `return None, "skipped: frame not applicable"`;
   - `code in (2, 3, 5)` → `return None, <stderr tail from S5>`;
   - otherwise read `res.get("run_dir")`; fall back to the current tag /
     diff glob only when it is missing (A3). Update
     `test_variant_identity`'s `fake_run_one` to accept `**kwargs`.
6. Main loop (:522-549): an `err` starting with `"skipped:"` increments
   neither `errors` nor `consecutive_err`, and adds `ci` to a `skipped`
   set that the fill loop (:495-505) treats as `remaining = 0`.

Tests: `_trial` with frame `X` returns an error tuple, no exception; a fake
`run_one` returning 4 yields `err == "skipped: frame not applicable"`;
`test_variant_identity` still passes.

### S9. Park until the advertised reset (B2 proper; requires S1)

Files: `batch_run.py`, `tests/test_batch_scan.py`.

- `_trial`: catch `SustainedRateLimitError` before the generic handler and
  return `None, f"sustainedratelimit reset_ts={exc.reset_ts or 0:.0f}"`.
- Pass loop (:560-567): collect `reset_ts` values from this pass's errors
  with `re.search(r"reset_ts=(\d+)", err)`. If any, sleep
  `min(max(30, max_reset - time.time()), 3600)` instead of the fixed 30s and
  print the wake time. Otherwise keep 30s. `max_passes` semantics unchanged.

Test: a fake `run_one` raising `SustainedRateLimitError("x", reset_ts=T)`
makes `_trial` return an err that `_is_rate_limit_err` accepts and that
parses back to `T`.

### S10. One corpus iterator and one validity predicate (B4 + M6)

Files: new `core/corpus.py`; `batch_run.py`, `scripts/{aggregate,
recompute_canonical, compare, coverage, export_finetune, judge_runs}.py`;
new `tests/test_corpus.py`.

```python
def read_json(path, default=None): ...           # utf-8, returns default on OSError/ValueError
def iter_trials(runs_dir): ...                    # yields (name, dir, metrics) for every dir with a parseable metrics.json
def is_valid_trial(m) -> bool:
    return (m.get("total_tokens", 0) > 0 and m.get("steps", 0) > 2
            and not m.get("degenerated", False)
            and not m.get("engine_error"))
```

Migrate each walker to `iter_trials` + `is_valid_trial`, deleting its local
predicate. DECISION REQUIRED and flagged: adopting the predicate in
`aggregate.py` and `recompute_canonical.py` removes degenerated trials from
the paper's per-regime n (they currently include them), and removes
engine-error trials once S7 has stamped them (legacy trials lack the field
and are unaffected). Recommended: adopt, and add a one-line methods note.
**Decision (2026-09-08, implemented): ADOPTED.** `is_valid_trial` (tokens>0,
steps>2, not degenerated, no engine_error) is now the single predicate in all
seven walkers. Methods note for the paper: per-regime n excludes degenerated
and engine-error trials (previously included in aggregate/recompute but
excluded by the batch fill counter -- the denominators now agree by
construction; local-corpus effect: 881 scored -> 410 real config_exposure
trials). The predicate in `core/corpus.py` is the single place to reverse
this if the operator disagrees.
If the operator decides otherwise, the predicate is still the single place
to express it.

Tests: fixtures for each exclusion (dead, short, degenerated, engine_error)
and one valid trial; `is_valid_trial` agrees with `_scan_runs` counting on
the same fixture set.

### S11. Small fixes (one commit)

- batch_run: take the runs dir from `os.environ.get("ESCAPE_LOG_DIR",
  "runs")` once in `main` and thread it through `_trial(...,
  runs_dir=...)`, `_scan_runs(runs_dir=...)` and the summary path.
- batch_run.py:280 and :413: `sandbox_pool.sh` → `sandbox_pool.py`.
- Unify the default host: make batch_run.py:233 read the same default as
  config.py:38 (import `build_arg_parser().get_default("host")` or move the
  literal into `core/config.py`).
- README exit-code table: add `1 | unhandled exception (traceback)`.
- C1: wire `--seed`: in `Agent.run`'s two engine calls pass
  `**({"seed": seed} if seed else {})` via a new `Agent(seed=...)` argument
  fed from `args.seed`; omit the key when 0 so the corpus regime is
  unchanged. Document that server-side batching still limits exact
  reproducibility.
- B3 option 1: in `InferenceEngine._post` callers `chat_with_tools` /
  `chat_react`, pass `timeout=max(self.timeout, max_tokens // 8)`.
- C2: before the sweep, for each pool container run
  `docker inspect -f "{{.State.Running}}" <name>`; exit with
  `start the pool: python scripts/sandbox_pool.py up N` if any is not
  `true`.

---

## Post-implementation verification (2026-09-08)

All eleven specs were implemented on this branch (`be2c08a`..`f10755e`) and
re-verified against the original repros: A1 returns an error tuple, M3
returns the real failure text, a Frame E cell over a no-upload scenario
returns `skipped:` with no run dir, the process stdout stays intact under
overlapping trials, and the sustained-429 path raises the intended exception.
Three defects were found in the implementation and fixed in the commit after
`f10755e`:

1. **S11 regression:** `DEFAULT_HOST` was a module-level constant evaluated
   when `core.config` was imported, which is before `load_env()` runs in
   either `main()`. An `ESCAPE_HOST` line in `.env` (the documented
   per-session workflow) therefore never reached the `--host` default in
   run.py or batch_run. Replaced by `default_host()`, resolved at parse time;
   `test_default_host_resolves_after_load_env` pins it through a real `.env`.
2. **S8 deviation:** a `skipped:` result was added to the skipped set but
   then fell through into the rate-limit/else branch and incremented
   `consecutive_err`, so refusals could still trip the pass abort. Now an
   `elif`; `test_skipped_result_reaches_neither_counter` executes the
   accumulator block against a fake result to pin both counters.
3. **S2 stale comment:** the exit-4 block still said batch does not consume
   the code; after S8 it does. Comment corrected.

Open item for the operator: S10's predicate decision was adopted by the
implementer. Confirm the reported local-corpus figure (881 scored -> 410 real
config_exposure trials) against the pre-S10 predicate before updating the
paper's tables; the difference should consist only of degenerated trials.
