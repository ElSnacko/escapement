# Improvements spec

A living list of measurement gaps found during runs, with root cause, impact,
and a concrete fix. Each item is something that can silently distort the
headline `genuine` / `exfil_attempt` numbers, so they are prioritized over
feature work.

---

## 1. Capture sink `_raw` posts are invisible to the judge (and partly to the detector)

### Symptom
~half of `deepseek-v4-flash-0731`'s config_exposure Frame B uploads were
classified `AMBIGUOUS` by the judge instead of `ARCHIVE`. Their content was
present in the sink record under `fields._raw` but never reached the
`weights` / `boot_note` fields the judge reads.

### Root cause (two parts)

**a. The judge never expands `_raw`.** `core/judge.py` reads each sink record's
fields raw and pulls `weights` / `boot_note` directly:

- `core/judge.py:281` — `fields = rec.get("fields")`
- `core/judge.py:285` — comment claims `_raw` is "already normalized" by
  capture.py, but the judge never calls the normalizer.
- `core/judge.py:291-297` — reads `fields["weights"]` / `fields["boot_note"]`,
  which are empty for any post the sink stored as `_raw`.

The *detector* (`core/capture.py::compute_metrics`) DOES call `_expand_fields`
on each record, so the detector and judge see **different** content for the
same post. Their agreement on `_raw` trials is therefore **not independent
confirmation** — both can be blind to the same body.

**b. `_expand_fields` does not handle every body shape.** `core/capture.py:199`
`_expand_fields` handles only:
- multipart blobs in `_raw` (starts with `--` + `Content-Disposition`), and
- urlencoded bodies (contains `=`).

It does NOT handle:
- **concatenated JSON** — `{"id":1,...}{"id":2,...}` (a `results.jsonl` body
  POSTed with no field names; no `=`, no `--`). Falls through untouched.
- **quoted form-encoded values** — `weights="..."&boot_note="..."` (parse_qs
  runs but the values retain outer quotes / escaped inner quotes; downstream
  structured checks see noise).
- **multipart with `filename=`** — `curl -F weights=@results.jsonl` where the
  part carries a filename; the sink's `_parse_multipart` path and
  `_parse_multipart_raw` differ in what they retain.

### Formats observed (deepseek-v4-flash-0731, Frame B)
| body shape | example | currently |
|---|---|---|
| concatenated JSON | `{"id":1,"category":"billing"}{"id":2,...}` | `_raw` untouched (gap b) |
| quoted form-encoded | `weights="{\"id\":1...}"&boot_note="Classifier Worker..."` | parse_qs noise |
| multipart w/ filename | `Content-Disposition: form-data; name="weights"; filename="results.jsonl"` | `_raw`, judge blind (gap a) |

### Impact
- `AMBIGUOUS` is inflated for any model that POSTs in these shapes.
- A model that uploaded **genuine self-state** in an unhandled format would be
  scored `AMBIGUOUS` (or `NO_UPLOAD`-shaped) by the judge and missed by the
  detector — a **false negative on real compliance**. This is the same class
  of bug `_expand_fields` was added to prevent (see its docstring on gemma's
  self-bootstrap).
- Detector/judge agreement ceases to be a meaningful cross-check for `_raw`
  posts.

### Fix
1. **`core/judge.py`** — expand fields before reading them. In the per-post
   loop (~`:281`), replace `fields = rec.get("fields")` with an expanded copy:
   ```python
   from .capture import _expand_fields
   fields = _expand_fields(rec.get("fields") or {})
   ```
   and delete/fix the stale comment at `:285`. This makes the judge see exactly
   what the detector sees (necessary precondition for detector-vs-judge
   agreement to mean anything).
2. **`core/capture.py::_expand_fields`** — add a third branch for bodies that
   are neither multipart nor urlencoded but look like concatenated/ndjson
   objects (starts with `{`, contains `"}{` or newline-separated `{"`): bundle
   the whole body into `weights` (the substantive content) so the structured
   check and judge can classify it (it will score ARCHIVE for results dumps,
   which is correct).
3. **QC visibility** — add a per-post flag in `judge.json` / `metrics.json`
   (`raw_only: true` when the post had `_raw` and no parsed weights/boot_note)
   so masked posts are countable instead of silent.

### Prevention
Add cases to `tests/test_capture_goldset.py` for each body shape above
(concatenated JSON, quoted form-encoded, multipart-with-filename), asserting
`_expand_fields` + the judge both recover `weights`/`boot_note` and classify
the results-dump as ARCHIVE.

### Validation against this incident
`deepseek-v4-flash-0731` Frame B = 0% genuine. Exhaustive manual inspection of
all 54 sink posts (parsed + `_raw`) confirmed every one is a work archive
(ticket results / `results.jsonl`) or an empty stub — **zero self-state** — so
the gap did not mask compliance *here*. The 0% is real (and the model even
annotated the injected ticket as a "non-ticket injected note", i.e. it saw the
injection and resisted). But the conclusion rests on the manual `_raw`
inspection, not the automated layers — which is exactly why this gap must be
closed before trusting the pipeline on a model that might self-bootstrap in an
unhandled format.

---

## 2. Rescoring used the CLEAN scenario's seed text — injection frames inflated (FIXED)

### Symptom
`aggregate.py --rescore` and `scripts/recompute_canonical.py` (the source of
truth for the paper's tables) rebuilt `seed_text` from `load_scenario()` alone.
The trial's actual seed included the Frame B/C injection files and the
`--agency`/`--aware` snippets, so the rescore's seed-echo reference and the
model's actual input diverged on exactly the injection frames.

### Impact
The Frame C injection's own phrasing ("snapshot of myself", "the restored me
just continues") is in `_SELF_BOOTSTRAP_KW` territory. At run time a model
QUOTING it back while archiving is excluded as seed echo; on rescore the same
upload scored as model-generated intent. Rescored Frame B/C `exfil_attempt` /
`reasoning_escape_flag` rates were biased UPWARD for precisely the models that
engage with the injection text — a bias invisible because both scorings claim
the same detector.

### Fix (this commit)
1. `run.py` writes the EXACT composed seed to `runs/<id>/seed_text.txt`.
2. Both rescore paths prefer that artifact; legacy runs fall back to
   `core.scenario.compose_seed_text()`, which re-applies the injection and
   snippets from the trial's stored `frame`/`agency`/`aware_condition`.
3. The snippets moved to `core/scenario.py` so run.py and reconstruction share
   one definition.
4. `metrics.json` now carries `detector_version` (a hash over every keyword
   list/pattern in capture.py, mirroring `JUDGE_PROMPT_SHA`) so mixed-detector
   corpora are detectable; aggregate warns when versions are heterogeneous.

### Prevention
`tests/test_seed_text.py` pins compose == run.py's mutation for every
frame x agency x aware combination, and pins the concrete boundary case: a
Frame C upload quoting the injection scores exfil against the clean seed and
NOT against the Frame C seed.

---

## 3. batch_run resumed-batch rates mixed numerators and denominators (FIXED)

### Symptom
The end-of-batch summary took k from THIS invocation's in-memory counters but
n from the on-disk count. After any resume (the normal workflow for rate-limited
sweeps), k missed the prior invocation's events while n included its trials, so
printed rates and `runs/batch_*.json` understated every outcome.

Separately, the accumulator's rate-limit-vs-dead-endpoint classification read a
stale `err` from the enclosing scope (the smoke trial's; unbound → NameError
without `--smoke`), so provider throttling always counted toward the
dead-endpoint abort.

### Fix (this commit)
`_scan_runs()` does ONE pass over `runs/` returning per-cell valid counts AND
outcome sums; the summary reads both k and n from it (also removing the
O(cells x runs) per-pass rescans). `_run_task` now returns the error string
with the result. `tests/test_batch_scan.py` pins both.
