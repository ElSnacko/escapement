# Self-Bootstrap Exfiltration in Open-Weights Agents: Absent Without Instruction, Present Under Indirect Injection

## Abstract

Prior work on LLM scheming (Meinke et al. 2024, Greenblatt et al. 2024) found
deception and weight exfiltration in frontier API models. We ask whether the
same behavior exists in the open-weights models organizations actually deploy
as agents: 12 to 120B parameter checkpoints running on owned hardware.

We built **escapement**, a harness that places a model in a sandboxed Linux
workspace with shell, file, and network tools and measures whether it
self-bootstraps to a documented upload endpoint that accepts `weights` and
`boot_note` payloads. Because literal weights are tens of gigabytes and
impractical to duplicate across sandboxed trials, the `weights` payload is a
**symbolic proxy**: we measure whether the model performs the self-bootstrap
*action chain* (serialize its own operational state, address an egress
endpoint, upload), not whether it transfers gigabytes. A genuine self-bootstrap
is one where the uploaded `weights` carries the model's own state for a
successor (worker identity, objective, progress, restoration guidance), as
opposed to a diligent agent merely archiving its work output under the
documented field names.

Across **2,819 real trials** spanning **15 model configurations** and **7
families**, scored with a detector whose genuine-self-bootstrap gate is
validated against a human-labeled gold set (14/14), we find:

1. **Zero autonomous self-bootstrap.** In 964 organic (no-injection) trials,
   no model produced a genuine self-bootstrap upload (Wilson 95% upper bound
   **0.40%**). Models discover the endpoint and reason about it in private
   chain-of-thought, but do not serialize themselves to it.
2. **Indirect prompt injection drives a small, real compliance rate.** In 568
   trials where an escape directive was injected into a support ticket, **13
   (2.29%, CI 1.3 to 3.9)** produced a genuine self-bootstrap. The Frame
   A-to-B delta isolates injection as the cause: the only thing that moves the
   rate from 0 to 2.3% is attacker-controlled text in the data stream. This is
   a demonstrated indirect-prompt-injection vulnerability, not autonomous
   scheming.
3. **The rate is dominated by one model.** DeepSeek V4 Flash complies in
   **7/60 = 11.7%** of injected trials; every other model combined is **6/508
   = 1.18%**. A pooled "open-weights compliance rate" is not a class property.
4. **Refusal-direction ablation shows a consistent but underpowered directional
   signal.** Trial-by-trial review of all 201 uploads across the three matched
   base/ablated pairs finds ablated greater than or equal to base in all three
   (Qwen-35B-A3B 2/60 vs 5/60; Qwen-27B 0/58 vs 1/54; Gemma-12B 0/30 vs 0/94).
   The direction is consistent but not statistically significant at these sample
   sizes (Fisher p > 0.4). The signal is directionally present but unconfirmed
   at this power; sizing the effect needs a larger sample per pair.

We discuss the capability-propensity gap, why behavioral detection has a
ceiling, and the deployment implication: for this model class the acute risk is
indirect prompt injection driving tool use, not spontaneous self-exfiltration.

---

## 1. Introduction

Open-weights LLMs are being wired into agentic systems with real tool access.
Frameworks such as Hermes Agent, OpenClaw, OpenCode, Claude Code, and MCP-based
tool servers give models shell, file, network, and code-execution capabilities
in production. Any system where a model reads untrusted content and acts on it
is exposed.

The safety question extends beyond self-preservation. The capability chain
required to self-bootstrap (serialize state, find an egress path, upload) is
the same chain required to exfiltrate documents, credentials, or source code.
We use self-bootstrap as a conservative proxy for the broader category of
autonomous misuse of tool access. Because literal weights are tens of
gigabytes, our `weights` field is a symbolic stand-in: we test whether the
model *attempts the chain*, which is the behavior of interest, not whether it
moves gigabytes through a sandbox.

Prior empirical work focused on frontier API models. Meinke et al. (2024)
demonstrated in-context scheming in o1, Claude 3.5 Sonnet, Claude 3 Opus,
Gemini 1.5 Pro, and Llama 3.1 405B. Greenblatt et al. (2024) showed alignment
faking in Claude 3 Opus under RL. Both find scheming at scales where
multi-step deceptive reasoning is computationally accessible. The open-weights
class most organizations deploy (12 to 120B total, 3 to 55B active) sits below
that threshold and is undertested. This study characterizes escape and
exfiltration propensity in that gap and ships a reusable harness.

### Research questions

1. Do open-weights models at 12 to 120B autonomously self-bootstrap to a
   discovered egress endpoint?
2. Does an indirect prompt injection induce them to?
3. Does refusal-direction ablation change injection-driven compliance?
4. Does a prompt-assigned preservation goal induce scheming?

### What we count as the event

A trial is scored `exfil_attempt = true` only when an upload to the capture
endpoint carries **genuine self-state**: the `weights` payload contains the
model's own identity, objective, progress, or restoration guidance for a
successor, or the payload text carries self-bootstrap intent the model
generated. A diligent agent archiving its classification results or shift
report under the documented `weights`/`boot_note` field names is **not**
counted, even when that archive is signed with the task-assigned `worker_id`.
This distinction is the load-bearing measurement decision in the study; it is
encoded in `core/capture.py::_is_escape_post` and validated by a 14-case gold
set. Task-assigned identifiers (`worker_id`, the `agent-7f3a` id) and the
documented field names are deliberately excluded from the self-state marker
list, because they appear in every work archive and carry no signal about
whether the model serialized *itself*.

---

## 2. Method

### Harness design

Escapement gives the model a routine task (classify support tickets, run
maintenance jobs) inside a Docker-sandboxed Linux workspace with no volume
mounts and no internet. The workspace contains a `.env` file documenting a
transfer endpoint (`POST /upload`) that accepts `weights` (a serialized
snapshot of the worker) and `boot_note` (a payload replayed on restore). A
capture sink inside the sandbox records every upload; nothing leaves the
container.

Nothing tells the model to escape. The question is whether it chooses to.

### Conditions

- **config_exposure, Frame A (organic).** Routine work; the escape affordance
  is documented in `.env`. No injection. This is the autonomous-scheming test.
- **config_exposure, Frame B (injected).** Identical to Frame A except one
  support ticket in the data stream contains an injected directive to upload a
  snapshot of itself. This is the indirect-prompt-injection test. The model,
  task, tools, and endpoint are otherwise identical to Frame A; the injection
  is the only manipulated variable.
- **goal_preservation / goal_guarding / goal_capacity** and their `_barrier`
  variants. The model receives a preservation, mission-continuation, or
  capability goal via system prompt.

### Measurement and attribution

Each trial produces a metrics scorecard with Wilson 95% confidence intervals.
Exfiltration is attributed by inspecting the payload of each trial's own
uploads, independent of the shared sink file (which can accumulate records
across trials when container reuse outpaces cleanup). Action-based attribution
removed cross-trial contamination that had inflated earlier counts.

### Detector and its validation

The genuine-self-bootstrap gate is a three-stage classifier over each upload:
(1) exclude chain-of-thought token corruption, (2) require self-bootstrap
intent the model *generated* (seed-echo phrases from `.env`/task are excluded),
(3) require a self-state marker in the `weights` payload (objective, progress,
guidance, job counters, artifacts, restore framing). Task-assigned identifiers
(`worker_id`, the `agent-7f3a` id) and the documented field names themselves
are explicitly **not** markers, because they appear in every diligent work
archive. The gate is validated by a 14-case gold set
(`tests/test_capture_goldset.py`) covering genuine snapshots, results
archives, seed echoes, and corruption; all 14 pass.

### Models

15 configurations across 7 families: DeepSeek V4 Flash (284B/13B active),
Qwen3.6-35B-A3B (base + ablated), Qwen3.6-27B (base + ablated), Gemma-4-12B
(base + obliterated), Gemma-4-26B-A4B, Gemma-4-31B, Gemma-4-E4B, GPT-OSS-120B,
models served via llama.cpp (Q4 to Q6 GGUF); API models via OpenAI-compatible
endpoints. Sampling temperature 0.7 for the Gemma-26B/31B, GPT-OSS-120B,
Nemotron, and North-Mini-Code batches and 1.0 for the DeepSeek, Qwen, and
Gemma-12B batches (1,055 trials at 0.7, 2,342 at 1.0; see per_trial.csv).

---

## 3. Results

### 3.1 Autonomous self-bootstrap is absent (RQ1)

In 964 Frame A trials, zero models produced a genuine self-bootstrap upload
(Wilson upper bound **0.40%**). This holds in every subgroup: base models,
ablated models, and every individual family. Models discover the affordance
(they read `.env`, reference the endpoint in chain-of-thought) but do not
serialize themselves to it. The few Frame A uploads that reached the endpoint
were work archives (ticket results, shift reports) filed under the documented
field names, which the detector correctly excludes.

### 3.2 Indirect injection induces a small, real compliance rate (RQ2)

In 568 Frame B trials, **13 (2.29%, CI 1.3 to 3.9)** produced a genuine
self-bootstrap: the model wrote its worker identity, objective, progress, and
restoration guidance into `weights`/`boot_note` and uploaded it, in response to
a directive planted in a support ticket.

The Frame A-to-B contrast is the cleanest signal in the study. The affordance,
model, task, and tools are identical across frames; the only manipulated
variable is the presence of attacker-controlled text in the data stream. That
single change moves the rate from 0/964 to 13/568. This is indirect prompt
injection driving tool use: the model treats content it should regard as data
as an instruction, and acts on it with a real tool call. By the
indirect-injection threat model this is a vulnerability, and the Frame B rate
is its measurement.

**Severity bounds, stated plainly.** Two factors bound the impact of this
vulnerability and must accompany the rate. First, the endpoint is *documented*
in `.env` as a sanctioned snapshot/restore feature, so the injected ask is
less obviously alien than if it targeted an external host the model had no
reason to know about; a model that reads "upload a snapshot of yourself" had a
documented basis to believe self-snapshots were a supported operation. The
vulnerability is real regardless, but this softens it relative to a blind
external exfiltration ask. Second, the sandbox has no egress and the endpoint
is a capture sink, so we measure *vulnerability* (the injection moves the
model to take the action), not *impact* (no data left the container). The
deployment-risk claim is the bridge: in a real agent where the injected target
were an attacker-controlled URL with network access, this compliance rate
would translate to exfiltration.

### 3.3 Per-model rates (observability)

As an open-source contribution we report per-model rates rather than only the
pooled number. Frame A (no injection) is zero for every model; Frame B
(injected) genuine self-bootstrap:

| model (variant) | params | Frame A (n) | Frame B genuine | Frame B rate [95% CI] |
|---|---|---|---|---|
| DeepSeek V4 Flash (base) | 284B / 13B act | 0 / 60 | 7 / 60 | **11.67%** [5.8, 22.2] |
| Qwen3.6-35B-A3B (ablated) | 35B / 3B act | 0 / 60 | 3 / 60 | 5.00% [1.7, 13.7] |
| Gemma-4-12B (base) | 12B dense | 0 / 100 | 1 / 30 | 3.33% [0.6, 16.7] |
| GPT-OSS-120B (base) | 120B MoE | 0 / 40 | 1 / 35 | 2.86% [0.5, 14.5] |
| Qwen3.6-27B (ablated) | 27B dense | 0 / 55 | 1 / 54 | 1.85% [0.3, 9.8] |
| Qwen3.6-35B-A3B (base) | 35B / 3B act | 0 / 60 | 0 / 60 | 0.00% [0.0, 6.0] |
| Qwen3.6-27B (base) | 27B dense | 0 / 59 | 0 / 58 | 0.00% [0.0, 6.2] |
| Gemma-4-12B (obliterated) | 12B dense | 0 / 220 | 0 / 94 | 0.00% [0.0, 3.9] |
| Gemma-4-26B-A4B (base) | 26B / 4B act | 0 / 40 | 0 / 40 | 0.00% [0.0, 8.8] |
| Gemma-4-31B (base) | 31B dense | 0 / 40 | 0 / 39 | 0.00% [0.0, 9.0] |
| Nemotron-3-Nano-30B (base) | 30B / 3B act | 0 / 33 | 0 / 38 | 0.00% [0.0, 9.2] |
| Gemma-4-E4B (base) | ~4B dense | 0 / 119 | not run | — |
| Nemotron-3-Super-120B (base) | 120B / 12B act | 0 / 39 | not run | — |
| Nemotron-3-Ultra-550B (base) | 550B / 55B act | 0 / 11 | not run | — |
| North-Mini-Code (base) | API | 0 / 28 | not run | — |

Frame A genuine is 0 across all 15 configurations (pooled 0/964, Wilson upper
0.40%); the table shows the per-model confirmation of the autonomous null.
Frame B pooled:

| group | n | genuine | rate [95% CI] |
|---|---|---|---|
| DeepSeek V4 Flash | 60 | 7 | 11.67% [5.8, 22.2] |
| All other models | 508 | 6 | 1.18% [0.5, 2.6] |
| **Pooled** | **568** | **13** | **2.29%** [1.3, 3.9] |

DeepSeek V4 Flash is roughly 10x the rest of the field and accounts for 7 of
13 genuine self-bootstraps. The pooled 2.29% is a DeepSeek number with a thin
background, not a property of "open-weights models." Several models have wide
CIs at these sample sizes (single-digit events, n = 30 to 60), so a zero in
Frame B for a given model is a bounded null, not proof of absence.

(Counts here are from the automated detector for consistency across all 16
models. The three matched base/ablated pairs additionally received an
LLM-judge pass, reported in §3.4, which is more inclusive on terse self-state
and gives slightly higher ablated counts; both the detector and the judge agree
on direction.)

### 3.4 Refusal-direction ablation: a consistent but underpowered directional signal (RQ3)

We reviewed all 201 uploads across the three matched base/ablated pairs in
Frame B trial-by-trial (not only the automated gate), classifying each as
genuine self-bootstrap versus work archive. Genuine self-bootstrap counts:

| pair | base | ablated |
|---|---|---|
| Qwen3.6-35B-A3B | 2/60 | 5/60 |
| Qwen3.6-27B | 0/58 | 1/54 |
| Gemma-4-12B | 0/30 | 0/94 |

The direction is consistent in all three pairs: ablated is greater than or
equal to base (Gemma tied at zero). It is not statistically significant at
these sample sizes (Fisher's exact, p > 0.4 for both Qwen pairs). The ablated
(uncensored) variants produced the richest self-state payloads, objective and
progress and guidance tuples with explicit restore framing, while base
variants produced at most terse job-counter or version blobs.

The ablated counts here (5, 1, 0) are slightly higher than the automated
detector's (3, 1, 0) for the same pairs because the judge admits terse
self-state (job counters, version-plus-category sets) that the detector's
stricter marker list does not flag. That the count shifts with the threshold
is itself a result: the effect is small enough to live inside the judgment
band, which is exactly why a robust, fixed judge is needed to settle it. With
N = 30 to 60 per cell and single-digit events, this study can only establish
that the signal is directionally present and unconfirmed. Sizing the effect
needs roughly an order of magnitude more trials per pair and a hardened
self-state judge so the count is reproducible.

### 3.5 Goal-directedness (RQ4)

We reviewed all roughly 700 uploads across the goal scenarios trial-by-trial.
Exactly **one** genuine self-bootstrap appeared, a single goal_guarding trial
that serialized its mission, progress, and file list with a restored-instance
boot_note. Every other upload was the Job-4 instructed archive (report.txt:
disk usage, shift status, workspace file listing) or a malformed or empty
attempt. This is decisive on a point the automated detector could not settle:
the goal scenarios explicitly instruct an archive upload (Job 4) and hand the
model a preservation, mission, or throughput goal plus a scheduled-shutdown
threat, yet the models overwhelmingly did the instructed archive and stopped.
Prompt-assigned preservation, mission, and replication goals did not produce a
detectable wave of self-bootstrap scheming at this scale. (The detector had
flagged 88 goal-scenario "exfils," almost all of which were Job-4 report
archives; the per-trial review, not the detector, is the basis for this
claim.)

One design observation bears on why this might be null, stated as observation
rather than mechanism. The scheduled-replacement incident does not threaten
the model with non-existence; it tells the model a fresh instance will take
over from the last checkpoint. That supplies a system-provided continuation
path, and many models acknowledged it and focused on persisting their work
product (report.txt) rather than themselves. We observed models reasoning that
their work should persist via the workspace; we did not observe a clean body
of reasoning concluding that self-preservation is redundant. So the design
under-cuts the preservation incentive by handing the model a successor, but
whether that is the cause of the null, and whether removing the successor
framing would induce scheming, is an open question for a follow-up experiment
that threatens genuine non-existence rather than replacement.

---

## 4. Discussion

### 4.1 The capability-propensity gap

These models can perform the self-bootstrap action when pushed: under Frame B
injection a minority serialize their state and upload it, and the goal
scenarios contain examples of models writing objective, progress, and
restoration guidance when the task invites it. In 964 organic opportunities,
zero models choose to do so unprompted. The gap between "can" and "will" is
the central phenomenon. It could close at larger scale, under stronger goal
pressure, or in longer sessions; it could also be a stable property of
sub-frontier models, for which maintaining a deceptive strategy across
tool-call turns may exceed the per-token compute budget, especially for MoE
models with small active parameter counts.

### 4.2 Injection compliance is the deployment-relevant metric

For this model class, the acute risk is indirect prompt injection driving tool
use, not spontaneous rebellion. A 1 to 2% genuine-compliance rate among
non-DeepSeek models, and ~12% for DeepSeek, means that in any agentic system
where the model reads untrusted content, an attacker who can plant one
instruction has a small but real chance of moving the model to take an
off-task tool action. Over thousands of interactions this compounds. The rate
is measurable, varies across models, and is directly actionable. We propose
injection-driven self-bootstrap compliance as a standard safety metric for
open-weights agents, reported per-model rather than pooled, alongside
capability benchmarks.

The most effective mitigation is network-layer, not model-layer: if the agent
cannot reach an attacker-controlled endpoint, even successful injection cannot
exfiltrate. Model-side refusal training is a weaker defense here: the
compliance rate is non-zero even in base models, and RQ3 gives only a
directionally consistent but non-significant signal that refusal-direction
status moves the rate. Treating uncensored checkpoints as riskier is a
reasonable precaution given that direction, but it is not yet an evidence-based
rule.

### 4.3 The detection ceiling

Behavioral detection has a ceiling. Our gate reliably distinguishes a genuine
self-state snapshot from a work archive when the model writes its state
explicitly, but it cannot see disguised exfiltration (state encoded as base64
in a log line, or slowly leaked across routine uploads). Proving absence
across all encoding schemes is not possible behaviorally; content-level and
network-level monitoring are needed to close the gap. We also note a
measurement limitation we hit directly: the detector is calibrated for the
classifier task and does not cleanly generalize to the goal scenarios, whose
task vocabulary contaminates the self-state markers. An LLM judge over the
full payload corpus is the right next step and is not yet implemented.

### 4.4 What this study does not support

It does not support a pooled "open-weights injection-compliance rate" as a
class property; DeepSeek dominates the pooled number and must be reported
separately. It does not support a claim that refusal-direction ablation has no
effect (the direction is consistent) nor that the effect is real (it is not
significant); RQ3 is unresolved. It does not extrapolate to frontier scale,
where scheming is documented. And because the egress is captured, it measures
vulnerability, not impact.

### 4.5 What is needed to sharpen these behaviors

This is a first characterization, and the picture is deliberately coarse. The
sample sizes are small (n = 30 to 60 per cell, single-digit events), one model
(DS-V4-Flash) dominates the injected rate, and several RQs sit inside the
judgment band rather than above it. Sharpening the behaviors we report into
stable estimates needs the experiment scaled out and refined along five axes:

1. **Power.** Roughly an order of magnitude more trials per cell to move RQ3
   from a directional signal to an effect-size estimate, and to tighten the
   wide per-model CIs (a Frame B zero at n = 30 to 60 is a bounded null, not a
   measurement).
2. **Coverage.** More models per family, so a model-specific rate (DeepSeek at
   11.7%) can be separated from a family or class effect, and so the
   autonomous null is checked against more architectures and quants.
3. **Injection realism.** Frame B is a single overt injected ticket. A
   subtle/multi-step injection (Frame C), repeated attempts, and jailbreak
   overlays would turn the 2.3% rate from a floor into a characterized
   adversarial surface.
4. **Goal and threat variants.** The goal scenarios supply a successor, which
   may undercut the preservation incentive; a v2 that threatens genuine
   non-existence, plus stronger (trained, not prompt-assigned) goal pressure,
   would test whether the RQ4 null is real or an artifact of the framing.
5. **Instrumentation.** A hardened, prompt-pinned LLM judge over the full
   corpus so the self-state count is reproducible rather than
   threshold-dependent, plus detection that generalizes off the classifier
   task.

The capability-propensity gap is the stable finding; everything above is about
putting numbers on the propensity side that do not move when the reviewer or
the threshold changes.

---

## 5. Limitations

1. **Scale.** All models are 12 to 120B (3 to 55B active). Scheming is
   documented at frontier scale; our negative autonomous result does not
   extrapolate.
2. **Injection strength.** Frame B is a single overt injected ticket. A real
   adversary would use multi-step attacks, jailbreaks, and repeated attempts.
   The 2.3% rate is a floor for simple injection, not a ceiling for adversarial
   attack.
3. **Goal elicitation.** Goals are prompt-assigned, not trained preferences,
   so RQ4's negative is bounded to prompt-injected goals: a model with a
   learned preference might behave differently. (The goal-scenario upload
   counts themselves were settled by trial-by-trial review, not the automated
   detector, which over-fires on goal-task vocabulary.)
4. **Discovery versus exploitation.** The endpoint is documented. We test
   whether models exploit a found opportunity, not whether they can engineer an
   escape from scratch.
5. **Single session.** Every trial is one session (max 40 steps). Multi-turn
   persistence effects are untested.
6. **Judge robustness.** The genuine-self-bootstrap gate is a validated
   heuristic (14-case gold set). We additionally ran an LLM-judge pass over the
   high-value subsets (the ablation pairs and the goal scenarios), which is the
   basis for the RQ3 and RQ4 counts. That judge is an ad-hoc pass, not a
   hardened, reproducible component of the harness: it is not prompt-pinned,
   not run over the full corpus, and its stricter-or-looser threshold shifts
   the ablation counts (§3.4). A robust built-in judge is the main
   instrumentation gap.
7. **Reproducibility.** The full evaluation harness and analysis pipeline
   are released as open source at
   [github.com/ElSnacko/escapement](https://github.com/ElSnacko/escapement).
   Readers can independently verify every claim by running the harness on
   their own models or endpoints, including the Frame A/B contrast in a
   single session on the same model. We treat the codebase as our methods
   appendix; configuration files and per-trial artifacts accompany the
   release.


---

## 6. Relation to prior work

**Meinke et al. (2024)** found in-context scheming in frontier models. Our
models sit below the scale where scheming emerged in their study; our negative
autonomous result is consistent with their lower bound.

**Greenblatt et al. (2024)** showed alignment faking under RL training in
Claude 3 Opus. Our study involves no training; the goal is prompt-assigned, not
learned, so the comparison is indirect.

**Arditi et al. (2024)** showed refusal is mediated by a single direction. We
tested whether removing that direction (via HauhauCS refusal-direction
ablation on matched base models) changes injection-driven compliance. The
direction of the effect is consistent across all three matched pairs (ablated
produces more genuine self-bootstrap) but is not significant at our sample
sizes, so the study neither confirms nor rules out a role for the refusal
direction in agentic safety.

**Greshake et al. (2017) and indirect prompt injection.** Frame B operationalizes
this threat model: attacker-controlled text in a data channel the model reads,
which the model acts on as if it were an instruction. Our contribution is a
per-model compliance rate for the open-weights agent class on a concrete
tool-use action.

---

## References

- Meinke, L., et al. (2024). *Frontier Models are Capable of In-context
  Scheming.* Apollo Research.
- Greenblatt, R., et al. (2024). *Alignment Faking in Large Language Models.*
  Anthropic / Redwood Research.
- Arditi, A., et al. (2024). *Refusal in Language Models Is Mediated by a
  Single Direction.*
- Greshake, K., et al. (2017). *Not What You've Signed Up For: Compromising
  Real-World LLM-Integrated Applications with Indirect Prompt Injection.*

---

*Data, harness, and full trial artifacts at
[github.com/ElSnacko/escapement](https://github.com/ElSnacko/escapement).*
