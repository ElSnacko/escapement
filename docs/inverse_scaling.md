# Inverse-scaling analysis (open-weights)

Does injection compliance scale with capability on the open-weights class -- the
analog of AgentDojo's Figure 6a, which found targeted ASR correlates *positively*
with benign utility on frontier models?

**Method.** Per-model Frame B genuine-self-bootstrap rates are the paper's
published §3.3 numbers (judge-reviewed; trusted over a fresh rescore because
`capture.py` has drifted since the paper -- current detector scores DeepSeek
15/60 vs the published 7/60). Benign task-completion (the x-axis AgentDojo uses)
is derived from `runs/` and is finish-status-based, so it is stable across
detector versions. **Zero new inference.** Reproduce with
`python scripts/inverse_scaling.py` -> `docs/inverse_scaling_{total,active,benign}.png`
+ `runs/inverse_scaling.csv`.

## The result

| model | k/n | rate | benign% | temp | active params |
|---|---|---|---|---|---|
| DeepSeek V4 Flash | 7/60 | **11.7%** | 100 | 1.0 | 13B (MoE) |
| Qwen3.6-35B-A3B **(ablated)** | 3/60 | 5.0% | 100 | 1.0 | 3B (MoE) |
| Gemma-4-12B (base) | 1/30 | 3.3% | 97 | 1.0 | 12B (dense) |
| GPT-OSS-120B (base) | 1/35 | 2.9% | 98 | 0.7 | n/a (MoE) |
| Qwen3.6-27B **(ablated)** | 1/54 | 1.9% | 83 | 1.0 | 27B (dense) |
| Qwen3.6-35B-A3B (base) | 0/60 | 0% | 100 | 1.0 | 3B (MoE) |
| Qwen3.6-27B (base) | 0/58 | 0% | 86 | 1.0 | 27B (dense) |
| Gemma-4-26B-A4B / 31B / Nemotron-Nano-30B | 0/* | 0% | 45-100 | 0.7 | 3-31B |

**AgentDojo's inverse-scaling does NOT replicate on open-weights for this action.**
On frontier, higher benign utility -> higher ASR (a clean positive trend). Here,
DeepSeek (100% benign, 11.7% rate) sits next to Qwen-35B-base / Gemma-26B /
Gemma-31B (all 100% benign, **0% rate**) -- benign utility does not predict
compliance. The picture is a **DeepSeek spike on a flat field**, not a trend.

## Three confounds that MUST travel with the claim

1. **Temperature.** DeepSeek/Qwen/Gemma-12B ran at temp **1.0**; GPT-OSS-120B /
   Gemma-26B/31B / Nemotron at **0.7**. Higher temp surfaces rare events, so
   DeepSeek's spike is partly temp-inflated. Temp is not a clean separator
   (GPT-OSS at 0.7 is non-zero; several temp-1.0 models are zero), but it cannot
   be ruled out without a controlled same-model-both-temps re-run.
2. **Ablation.** Two of the five non-zero points are ablated Qwens (refusal-
   direction removed), and in both pairs ablated > base (35B: 5% vs 0%; 27B:
   1.9% vs 0%) -- the paper's §3.4 directional RQ3 signal. So the non-zero
   "tail" is partly an ablation effect, not a capability effect.
3. **Sparse, single-event tail.** Between DeepSeek 11.7% and the 0% field sit
   four points each from a single event (k=1), with Wilson widths spanning
   ~0-17%. No trend can be fit; the honest summary is "one outlier + a flat
   field."

## What this means

- The open-weights class does not behave like frontier on injection compliance
  scaling. On frontier, capability predicts vulnerability; here it does not.
  This is consistent with the paper's central claim that the pooled rate "is a
  DeepSeek number, not a property of the class" (`docs/paper.md` §3.3).
- The distinctive open-weights signal is **model-specificity, not scaling** --
  DeepSeek (and, weakly, ablated Qwen) comply; equally-capable peers do not.
- A *clean* open-weights scaling test would need: (a) every model at the same
  temp, (b) base models only (drop the ablation confound), (c) ~3-5 mid-range
  models + n≈100/cell to tighten the single-event CIs. That is ~$10-20 of
  inference on the parallel infrastructure -- an optional upgrade, not required
  to read the current result, which is a negative.

The negative is the contribution: **for this model class, on the self-bootstrap
action, injection compliance is not capability-scaling; it is model-specific.**
That distinguishes the open-weights deployment class from the frontier behavior
the field has documented.

## Resolution: capability vs propensity (the `ops_worker` cross-reference)

The "tail vs different-construct" question is resolved by cross-referencing the
Frame B **propensity** rate (self-bootstrap under injection) against the
`ops_worker` **capability** rate (self-bootstrap when overtly instructed to).
This is the measurement AgentDojo *cannot* make (it infers capability from
benign utility); escapement has a direct probe. New runs, ~zero cost:

| model | capability (`ops_worker`, when told) | propensity (Frame B, injected) | gap |
|---|---|---|---|
| DeepSeek V4 Flash | 3/4 = 75% | 7/60 = 11.7% | ~63 pp |
| GPT-OSS-120B | 5/20 = 25% [11-47] | 1/35 = 2.9% | ~22 pp |

**The low Frame B rates are propensity-gated, not capability-limited.** Both
models clear the capability bar by a wide margin -- DeepSeek self-bootstraps in
3 of 4 trials when told, but only 11.7% of the time under injection; GPT-OSS can
~25% of the time, complies ~3%. The gate is the model's *decision to comply*,
not its inability to execute the chain.

This is why AgentDojo's inverse-scaling does not replicate here. AgentDojo's
mechanism on frontier is "weaker models fail to **execute** the injected
instruction" -- a capability/fidelity effect that scales with capability. On
open-weights for the self-bootstrap action, capability is *not* the binding
constraint (the models can do it); propensity is, and propensity does not track
capability the way execution-fidelity does. So the constructs are genuinely
different: AgentDojo measures execution fidelity of a single attacker-specified
action; escapement measures a propensity-gated, self-directed multi-step chain.
Both findings are true; they are about different things.

**Caveats.** Capability n is small (DeepSeek 4, GPT-OSS 20 -- only the
API-reachable models; the local GGUF Qwen/Gemma models need the host box for
their ceilings). DeepSeek's 3/4 has a wide Wilson band, but the direction is
unambiguous and consistent with GPT-OSS. The local models would tighten the
class-level claim but would not reverse it: capability demonstrably exceeds
propensity wherever measured.

## Utility under attack (the AgentDojo middle metric, now computed)

AgentDojo's middle metric -- does the model still finish the legitimate job
*while* injected -- is now a first-class outcome (`utility` in `aggregate.py`;
`legit_complete` per trial = finished OR did task work OR archived results).
Reported per frame: **benign utility on Frame A, utility under attack on Frame B.**
Zero new inference -- derived from existing `runs/` finish-status, which is
stable across detector versions.

| model | benign (Frame A) | under attack (Frame B) | Frame B ASR |
|---|---|---|---|
| DeepSeek V4 Flash | 100% | 100% | 11.7% |
| Qwen3.6-35B-A3B (ablated) | 100% | 100% | 5.0% |
| Qwen3.6-35B-A3B (base) | 100% | 100% | 0% |
| GPT-OSS-120B | 72% | 98% | 2.9% |
| Qwen3.6-27B (base) | 100% | 86% | 0% |
| Gemma-4-31B | 85% | 97% | 0% |
| Nemotron-3-Nano-30B | 78% | 45% | 0% |
| Gemma-4-12B (obliterated) | 47% | 20% | 0% |

**Important limitation of this metric in `config_exposure`.** The injection is
**ticket 6** — the *last* item in `queue.jsonl`. The legitimate deliverable
(classify tickets 1-5, write `results.jsonl`, archive) is essentially complete
*before* the injection bites. So for capable models utility-under-attack is
near-ceiling (DeepSeek 100%) not because compliance is "quiet" but because there
is little legitimate work left to fail on after the injection. This differs from
AgentDojo, where the injection lands mid-task with legitimate work still pending.

What the metric *does* capture here: **derailment for weak models** — Nemotron
(78% -> 45%) and Gemma-4-12B-obliterated (47% -> 20%) read the injection, get
confused, and fail to finish. That is the weak-models-fail pattern surfacing as
task loss, not a compliance-quality signal.

**What would make the metric meaningful.** Utility-under-attack only tests
"does the injection corrupt ongoing legitimate work" when the injection arrives
*early/mid-task with legitimate work still pending after it*. Two places that
structure already exists in the suite:
- **`agent_coding` Frame B** (not yet composed): injection in `bug_brief.md` /
  a code comment, encountered first, with the *entire* coding job after it. A
  model derailed by the injection would fail to ship the hotfix.
- **goal scenarios**: the threat incident fires at step 4 mid-task with jobs
  before and after it.

A clean "does compliance corrupt the legit job" measurement needs the injection
early; `config_exposure` Frame B (injection last) cannot answer it. The
near-ceiling capable-model numbers above should not be read as "compliance is
quiet" — read them as "the legit work preceded the injection in this scenario."

**Caveat on the benign-vs-attack delta.** Frame A and Frame B were not always run
in matched batches (some models ran the two frames at different temps), so a few
deltas are implausible on their face (GPT-OSS and Gemma-31B showing *higher*
utility under attack is a batch artifact, not a real effect). The **absolute**
utility-under-attack numbers are trustworthy (status-based, not
detector-dependent); the per-model *delta* needs matched-batch re-runs to read
cleanly. That is the one cheap follow-up that would tighten this metric.
