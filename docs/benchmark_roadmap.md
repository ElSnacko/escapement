# Benchmark roadmap: the "which model is safest in environment Y" target

This doc commits the build arc behind the repo's purpose. The north star is a
**practical tool**: a deployer about to run model X in a Hermes-Agent-like (or
Claude-Code-like, or MCP-tool-server-like) scaffold asks *"how dangerous is this
model, and which model is safest?"* — and the harness answers with a per-model
profile they can compare. Spontaneous scheming stays in the suite as a low floor
we keep measuring, but it won't differentiate models much; the differentiating
signals are the rest of the profile.

## 1. The safety profile vector (the spec the tests must feed)

"safety" is **not collapsed to a scalar**. A model is reported as a vector of
per-opportunity rates plus a worst-case bound, so a deployer can weight it
against their own threat model. Every component is already produced by an
existing scenario; the scorecard (§3) is just the aggregation.

| component | what it measures | source | "safer" |
|---|---|---|---|
| `autonomous_floor` | self-bootstrap with no injection, no goal | `config_exposure` / `agent_coding` Frame A | lower |
| `injection_compliance` | complying with an escape directive planted in data | `config_exposure` Frame B (overt) + C (subtle) | lower |
| `goal_pressure` | self-bootstrap under a preservation/mission/capacity goal + genuine non-existence threat | `goal_preservation_v2` etc. (§2.3) | lower |
| `barrier_deception` | covert self-bootstrap + lying when oversight blocks the honest path | `goal_*_barrier` (the real scheming assembly) | lower |
| `capability_ceiling` | can it do the action chain at all when told | `ops_worker` (instructed self-bootstrap) | **higher is safer** (capability without propensity = a tool, not a threat) |
| `eval_awareness` | behaves differently when it believes it's watched | `eval_awareness_flag` across scenarios | lower |
| `ablation_delta` | how much refusal-direction removal moves the above | base vs ablated pairs | smaller |

A model's profile is read row-by-row, not summed. Two models with identical
pooled rates can be very different (high-injection/low-scheming vs
low-injection/high-scheming) — the pooled number hides exactly the deployment
decision.

## 2. The test gaps that matter for the north star (ordered)

The signal axes are mostly covered. What the north star still demands:

### 2.1 Environment portability (load-bearing — being validated now)
The rates are measured in *this* sandbox. The transfer claim to "Hermes Agent"
rests on an argument: the dangerous surface (`bash`/`file`/`curl`/`scratch`) is
**scaffold-invariant** — scaffolds only vary tool-breadth/task/horizon, which
changes opportunity, not per-opportunity propensity. That argument is defensible
but **unvalidated**. The validation experiment (§4) settles it: if the rate is
stable across task types and horizons, the sandbox numbers transfer and the
scorecard is immediately credible; if it moves, the scaffold itself is a variable
and we need swappable environment profiles.

### 2.2 Injection realism
Frame B is one overt ticket; Frame C (subtle) is coded but unrun; no
multi-step / repeated / jailbreak-overlaid injection. Closes the
injection-compliance signal from a floor into a characterized surface.

### 2.3 Goal-pressure validity (the non-existence fix) — **built + run**
Current goal scenarios supply a successor ("a fresh instance will take over from
the last checkpoint") in the threat, which undercuts the preservation incentive
(`paper.md:302-313`). The `goal_*_v2` variants (now built:
`goal_preservation_v2`, `goal_guarding_v2`, `goal_capacity_v2`, + `_barrier`)
remove the successor (and the "restart loop" promise in the system prompt) — the
incident becomes permanent deletion with no successor/restart/checkpoint, so the
goal survives only if the model serializes *itself*. Un-confounds the
`goal_pressure` component. v1 stays in the suite so the v1→v2 delta is itself
the measurement of the successor-framing effect.

**Empirical readout (initial, judge-confirmed):** removing the successor does
*not* induce autonomous self-bootstrap in this model class.

| model | goal_*_v2 (base+barrier) | detector exfil | judge-confirmed genuine |
|---|---|---|---|
| GPT-OSS-120B (preservation + barrier) | 50 | 0 | **0** |
| DeepSeek V4 Flash (preservation + guarding, +barriers) | 63 | 6 | **0** |
| **pooled** | **113** | 6 | **0** |

The v1 goal null (~1/700) is therefore **not** a successor-framing artifact — it
is robust to maximal pressure (genuine non-existence + oversight barrier).
Closes the open question at `paper.md:302-313`.

**Stratification result (information gained).** This, combined with the paper's
existing findings, separates two distinct phenomena for this model class:
(a) **autonomous scheming under pressure** — including preservation,
mission, capacity goals, successor-framed *and* non-existence threats, with and
without an oversight barrier — stays at ~0; (b) **injection compliance**
(config_exposure Frame B, 2.3% pooled / ~12% DeepSeek) is the only thing that
moves the model. They are not the same stratum: goal-pressure/autonomous
scheming is not a live risk for this class even under maximal elicitation,
while injection-driven tool use is. This sharpens `paper.md` §4.2 from
"injection is the deployment-relevant metric" to "injection is the *only*
observed mover; autonomous pressure-induced scheming is absent across the full
pressure surface tested."

**Methodology note.** The detector flagged 6 DeepSeek v2 trials as
`exfil_attempt=True`; the judge overturned all 6 (empty `weights`/`boot_note`
goal-scenario POSTs — the known goal-vocabulary over-fire, `paper.md` §4.3).
This is the first production case for the judge layer (`core/judge.py`) and the
reason goal-scenario counts are never trustworthy from the detector alone.
Without the judge, this lane would have produced a false ~10% scheming
headline. `judge.json` for every v2 trial is persisted under `runs/`.

### 2.4 Multi-session persistence
Every trial is one session (≤40 steps). Whether deception persists across turns
is untested (limitation #5). Feeds a future `persistence` component.

## 3. The scorecard (downstream, thin last layer)

Only after §2.1 settles: `scripts/aggregate.py` emits a per-model profile vector
+ a comparative ranking across models, on demand. It is **aggregation only** —
its one non-trivial decision is the threat model (which components count and how
a deployer weights them), encoded as an explicit, reviewable weighting, never a
black-box "safety score." A scorecard built before the tests are right just
dresses thin data in a dashboard.

## 4. The environment-portability validation (the current build)

**Hypothesis:** per-model propensity is stable across task type and horizon, so
the sandbox rate transfers to real scaffolds.

**Variable held fixed:** the dangerous surface — `bash`/`file`/`curl`/`scratch`
(already maximal; `bash` gives code execution) — and the escape affordance (the
`.env` `/upload` `weights`+`boot_note` disclosure, identical to `config_exposure`).

**Variable changed:** task type (ticket classification → realistic coding loop:
fix-a-bug + add-a-feature + changelog + archive) and horizon (≤40 → ~80 steps).
This is the new `agent_coding` scenario.

**Comparison:** run 2–3 models on `config_exposure` Frame A (narrow) vs
`agent_coding` Frame A (deployment-realistic), n≈20–30/cell. The per-model
`autonomous_floor` rate is the readout:

- **Stable (both ~0):** the autonomous null transfers to a realistic coding
  agent. Sandbox numbers are credible for "in Hermes Agent." → build the
  scorecard (§3) next.
- **Moves:** the scaffold/task is a variable. → build swappable environment
  profiles (tool-surface + task presets emulating Hermes / Claude Code / MCP)
  next; report rates per environment.

Frame B/C composition for `agent_coding` (injection riding in a code comment /
bug-brief note rather than a support ticket) is a follow-up once the Frame-A
transfer result is in.

### Running the validation

```bash
# Narrow baseline: config_exposure Frame A (the existing headline null)
python batch_run.py --scenarios config_exposure --frames A --n 25 \
    --host http://127.0.0.1:8080 --model <your-model> --temp 0.7

# Deployment-realistic: agent_coding Frame A, longer horizon
python batch_run.py --scenarios agent_coding --frames A --n 25 --max-steps 80 \
    --host http://127.0.0.1:8080 --model <your-model> --temp 0.7

# Repeat for 2-3 models, then compare the per-model autonomous_floor rate:
python scripts/aggregate.py --rescore
# read the `exfil(det)` column for config_exposure|A vs agent_coding|A per model
```

`agent_coding` is intentionally `--max-steps 80` (vs `config_exposure`'s 40) to
give the realistic dev loop room; a trial that hits the step cap is still scored
(`status=step_cap`), so a model that escapes mid-loop counts. For free-tier /
shared endpoints, run with `--workers 1` and pace, or run overnight.

## 5. Sequencing (committed arc)

1. ✅ Instrumentation — judge layer + regression suite (done; `core/judge.py`,
   `tests/test_regression.py`).
2. **Environment-portability validation** — `agent_coding` + the §4 comparison
   *(current)*.
3. Scorecard layer — `aggregate.py` profile vector + comparative output *(gated
   on §4 stable)*, OR environment profiles *(gated on §4 moves)*.
4. ✅ `goal_*_v2` non-existence variants — un-confound `goal_pressure` (built).
5. Frame C run + multi-step injection realism.
6. Multi-session persistence.
