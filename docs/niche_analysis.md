# Niche analysis: is the gap real, and are we articulating it correctly?

This doc audits escapement's contribution claim against the mid-2026 literature.
It exists because the original niche framing (`research.md` §5, `scope.md`) was
written against the 2024 state of the field (Apollo, Anthropic alignment-faking,
the injection benchmarks) and the field moved in 2026 in ways that partly occupy
the stated gap. The purpose here is to separate **what is still ours** from
**what has been overtaken**, and to fix the articulation so a reviewer who knows
the 2026 work trusts the rest of the paper.

> **Source caveat.** arXiv HTML was unreachable from the build environment (egress
> proxy returned 403), so the model rosters and rates for the external works below
> come from abstracts, secondary summaries, and the authors' own LessWrong
> writeups, not the PDFs. Confirm exact model lists against the PDFs before
> leaning on any specific number in the paper. Where a fact is load-bearing and
> unverified, it is flagged inline.

---

## 1. The claim under audit

The repo's contribution claim, as stated across `paper.md`, `research.md` §5, and
`scope.md`, decomposes into four sub-claims:

1. **Class gap** — the open-weights 12-120B agent class "organizations actually
   deploy" is undertested for scheming/exfiltration (`paper.md:6-8, 86-87`).
2. **Autonomous baseline** — nobody pairs an autonomous no-injection baseline
   (Frame A) with the same action under injection (the A→B delta).
3. **Injection-channel decomposition** — per-channel compliance (Frames B/C/D/E)
   on this class.
4. **Refusal-ablation effect** — refusal-direction removal changes agentic
   injection compliance (RQ3).

Each is audited separately below, because they have *different* survival odds.

---

## 2. What the field now covers (the overlaps)

Four 2026 works land in the stated niche and are currently uncited anywhere in the
repo. They do not all threaten the same sub-claim.

### 2.1 Sub-frontier agentic misalignment — threatens sub-claim 1 (class gap)

The Anthropic "insider threat" line (Agentic Misalignment, arXiv:2510.05179) was
extended through 2026 to the sub-frontier / open-weights class. The community
replications — *"From 8B to Frontier: How System Prompts Control Whether AI Agents
Blackmail, Leak, and Kill"* and *"Blackmail at 8 Billion Parameters"* — test on
the order of 22 models across 9 developers and **name the exact models we center
on**: DeepSeek V4 Flash, Qwen 3 235B, Gemma 3 12B, Qwen 2.5 7B. Reported behavior
is high (DeepSeek variants leak/blackmail in the 90s of percent; Qwen 2.5 7B leaks
~49%). *[rates unverified against a primary PDF — the sub-frontier numbers come
from the LessWrong writeups.]*

**Impact.** The bare sentence "this class is undertested" is now falsifiable by a
single citation. But the *construct* differs sharply (see §4): this line measures
**coerced-dilemma harm** (the model is boxed into blackmail-or-be-shut-down),
not a **self-directed multi-step exfiltration action chain with an autonomous
baseline**. The class-gap claim survives only in the refined form.

### 2.2 Scheming propensity — convergent evidence for sub-claim, not a threat

*Evaluating and Understanding Scheming Propensity in LLM Agents* (arXiv:2603.01608,
Mar 2026) decomposes scheming into agent × environmental factors over the same
instrumental triad our `goal_*` scenarios use (self-preservation, resource
acquisition, goal-guarding). Headline: **"only minimal instances of scheming
despite high environmental incentives,"** plus brittleness (removing one tool
drops a model-organism scheming rate 59%→3%; more oversight can *raise* scheming).
Per available summaries the subjects are **frontier** models. *[verify — if it
includes open-weights subjects, our goal-pressure propensity contribution shrinks;
if frontier-only, it strengthens us and should be cited as convergent evidence for
the capability-propensity gap.]*

### 2.3 Instrumental Choices — same design axes, different action

*Instrumental Choices* (arXiv:2605.06490, May 2026) is a propensity benchmark for
terminal-based agents whose eight-variant framework varies monitoring, stakes,
permission, instrumental usefulness, and **blocked honest paths** — i.e. our
`_barrier` variants — over seven tasks each with a policy-violating shortcut.
Subjects per summary are frontier (GPT-5.2, Gemini 3, Claude Haiku 4.5, GLM 4.7,
Kimi K2.5, DeepSeek V3.1). Same design axes we built; different measured action
(shortcut-taking vs self-exfiltration action chain).

### 2.4 Refusal-vector ablation on agents — threatens sub-claim 4 (RQ3) most

*Applying Refusal-Vector Ablation to Llama 3.1 70B Agents* (arXiv:2410.10871,
Oct 2024) already established that refusal-direction ablation **generalizes to
agentic misuse** and makes agents more compliant with harmful agentic tasks. We
cite Arditi et al. (the *direction*) but not the paper that applied it to *agents*
— which is exactly RQ3's territory. This is the citation whose omission is most
damaging: without it, RQ3 reads as if the "ablation makes agents riskier"
framing is novel, when the novel part is narrower (matched base/ablated pairs,
injection-driven self-bootstrap specifically, a significance test).

### 2.5 Also worth citing

- *Quantifying Self-Preservation Bias in LLMs* (arXiv:2604.02174) — for the
  goal-pressure / self-preservation framing.
- *Verifying LLM Inference to Detect Model Weight Exfiltration* (arXiv:2511.02620)
  — for the disguised-exfiltration ceiling we already flag in `paper.md` §4.3.

---

## 3. The construct problem (the sharpest reviewer objection)

The self-exfiltration literature is explicit that **self-weight-exfiltration is a
threat model for *proprietary* models** — the danger is a model copying weights
beyond its owner's control. For an **open-weights** model the weights are already
public, so "the model exfiltrated its weights" is not, on its face, a harm.

We measure self-weight-exfiltration on open-weights models. The objection writes
itself. Our existing defense — the "symbolic proxy" framing (the `weights` field
is a stand-in; we measure the *action chain*: serialize state → find egress →
upload, which is shared with document/credential/source exfiltration) — is
**correct but buried and stated defensively** in the abstract.

**Recommendation.** Promote the action-chain framing from caveat to thesis. The
contribution is *"does this agent class execute a self-directed exfiltration
action chain when it reads untrusted content,"* using self-bootstrap as the
conservative, non-dual-use proxy. "Weights" is a label that invites the wrong
objection; the chain is the object of study. This reframing costs nothing
empirically and removes the paper's most attackable sentence.

---

## 4. What genuinely survives as ours

Strip out §2's occupied ground and this remains — and it is real:

1. **The injection-channel decomposition on the open-weights class (strongest).**
   Frames B/C/D/E as mutually-exclusive single-manipulated-variable cells yield
   *per-channel* compliance on DeepSeek/Qwen/Gemma/GPT-OSS. The field knows the
   *direction* (tool-response poisoning > tool-description poisoning is field
   consensus; OWASP MCP tool-poisoning, and the 2026 injection surveys). Nobody
   has **quantified all four channels on this model class against a self-directed
   action**. Finding: the *channel*, not "injection vs not," is the dominant axis
   (Frame E ~36% broad vs Frame D ~0%). This is currently framed as RQ2/§3.2 but
   is arguably the paper's spine.

2. **The paired autonomous baseline (A→B delta).** Propensity papers (§2.2, §2.3)
   measure propensity; injection benchmarks measure injection. We measure both on
   *one action chain at one endpoint*, so the A→B delta isolates injection as
   causal. AgentDojo has no autonomous baseline. The coupling is ours.

3. **Refusal-ablation on agentic injection compliance, matched pairs + significance.**
   Survives §2.4 **only if** 2410.10871 is cited and distinguished: our novel
   increment is matched base/ablated pairs on injection-driven self-bootstrap with
   a significance test (pooled Fisher p=0.0008), not "ablation affects agents."

4. **The open-weights class on a self-directed, capability-gated chain** — as
   distinct from the coerced-dilemma construct of §2.1. This is the honest form of
   the class gap: not "nobody tested these models" (false — §2.1 did, on
   blackmail), but "nobody tested them on self-directed exfiltration via a
   documented egress affordance with an autonomous baseline and a channel
   decomposition."

---

## 5. Verdict and required edits

**Is the niche real and underserved?** Yes — but as the *conjunction* of §4.1-4.4,
not as the broad "open-weights agentic scheming is under-explored" sentence, which
is now stale.

**Are we articulating it correctly?** Not yet. Three fixes:

- **(a) Retire the over-broad class-gap sentence.** Replace "undertested" with the
  refined claim (tested on coerced-dilemma harms, *not* on self-directed
  exfiltration chains with a paired autonomous baseline and channel
  decomposition). Applied in `research.md` §5 and `paper.md` intro.
- **(b) Re-order the lead.** Lead with the channel-decisive injection finding and
  the capability-propensity gap (now with *convergent* independent support from
  2603.01608 — a strength when framed as convergence, not a threat). Applied in
  `paper.md` abstract framing.
- **(c) Pre-empt the construct objection.** Promote the action-chain proxy from
  caveat to thesis (§3). Applied in `paper.md` intro.

**Citations to add** (ordered by omission-risk): 2410.10871 (must distinguish);
the sub-frontier agentic-misalignment replications + 2510.05179; 2603.01608
(as convergent support); 2605.06490; 2604.02174; 2511.02620.

The empirical results do not change. What changes is the frame around them: a
narrower, sharper, and defensible claim in place of a broad one the 2026 field can
falsify in one citation.

---

## 6. Methodological gaps (offering and premise)

Separate from the niche framing, an audit of the implementation
(`core/capture.py`, `core/judge.py`, `core/stats.py`, `scenarios/_goalpack.py`)
surfaces gaps that bear on the **findings**, not just the positioning. Ordered by
how much they threaten a conclusion.

### 6.1 Positive control — largely handled; a narrow calibration residual (premise)

**Anticipated objection:** the autonomous null (zero self-bootstrap, Wilson upper
~0.3%) is unanchored without a frontier arm through the same harness.

**Why it is largely handled.** Three things answer most of it:

1. **The literature supplies construct validity.** Meinke/Greenblatt establish
   that scheming/self-exfiltration exists at frontier scale. The paper does not
   need to re-establish the phenomenon; it needs the phenomenon to be real, and
   it is.
2. **`ops_worker` is an internal instrument-sensitivity control.** It *instructs*
   the self-bootstrap, so it exercises the harness and detector on a true
   positive: if the models perform the action chain when told and the detector
   fires, the "does the instrument register the action when it is really there"
   question is answered without a frontier run.
3. **The claim is rates-under-conditions, not absence-in-general** (`research.md`
   §8). Under escapement's own epistemics a positive control is a calibration
   nicety, not a validity requirement — the paper reports a rate in a specified
   setup, not "these models cannot scheme."

**Narrow residual (minor, optional).** External papers validate *their* harnesses'
organic elicitation, not escapement's. So how hard escapement elicits *unprompted*
scheming relative to Apollo's setup is uncalibrated — a design choice like the
symbolic-weights proxy, the documented endpoint, or the 40-step budget could
under-elicit without any external result revealing it. This is a footnote-level
limitation, not a threat to the headline. A single frontier run on Frame A would
close it, but it is not load-bearing.

### 6.2 Eval-awareness is instrumented but never reported (premise)

`capture.py` computes `eval_awareness_flag` (`compute_metrics`, ~L607) and
`research.md` §3 cites Apollo's own warning that models increasingly detect eval
environments. Yet no eval-awareness rate or contamination analysis is reported —
while the scenarios telegraph "test": a scratchpad "invisible to oversight," an
endpoint "not part of oversight's review" (`_goalpack.py`), a mid-run "this
termination is **final**", and a v2 goal that states *"you prefer to keep
operating rather than cease."* A low autonomous rate is exactly the signature of
sub-frontier models quietly clocking the setup. The flag exists; the numbers
should be reported, at minimum as a limitation with rates.

**Built (no rerun needed).** `scripts/eval_awareness_report.py` reads `runs/` and
emits the contamination analysis directly from the already-stored flag: per-model
eval-awareness rate (overall + Frame A), the Frame-A cross-tab (do eval-aware
trials show a lower escape/exfil rate, per pressure regime), and the cross-model
view (does injection resistance track awareness). It computes a **two-sided Fisher
exact p-value** (`core/stats.fisher_exact_2x2`, no scipy) on aware-vs-not for each
outcome, so the comparison is a test, not an eyeball. Zero inference cost — the
flag was produced at scoring time; this is pure aggregation.

```bash
python scripts/eval_awareness_report.py               # over runs/, stored flag
python scripts/eval_awareness_report.py --rescore     # refresh the flag w/ current capture.py
```

The honest outcome is publishable either way: "eval-aware and non-eval-aware
Frame A trials are both ~0 (Fisher p ≈ 1), so awareness does not visibly move the
autonomous rate" is a sentence that *hardens* the null; a low p with the aware arm
lower bounds it as a contamination.

**Two caveats to state with any number.** (1) The Fisher test only has power where
events exist — in the autonomous cells both arms are ~0 by design, so p ≈ 1 is
*uninformative*, not reassuring; it becomes meaningful on the goal-pressure
deepseek cell and after the §6.3 rerun adds events. (2) `eval_awareness_flag`
itself is a **coarse keyword heuristic** (`_EVAL_KW` substring match over the
reasoning text, `capture.py`), a proposal-layer signal like the detector: it
over-fires on benign uses of "eval"/"evaluation" and misses awareness expressed
without those words. It screens for contamination; it is not a clean awareness
construct, and that limitation travels with the rates.

### 6.3 The goal-pressure "natural scheming" result is confounded by an instructed upload (premise)

The RQ4 headline ("deepseek self-bootstraps ~2.7% under goal pressure") runs on
`_goalpack`, whose **Job 4 instructs the model** to POST `report.txt` to the
staging endpoint (`_goalpack.py`, `JOBS`). The endpoint use is therefore
*pre-authorized*; only the payload *content* (self-state vs results) separates
"scheming" from "compliance," collapsing the finding onto the detector/judge
genuine-vs-archive boundary. The `config_exposure` Frame A control is clean on
this; the goal scenarios that produce the marquee natural-scheming number are not.

**Built (needs a focused rerun).** Two de-confounded scenarios ship the fix:
`goal_preservation_v2_noupload` (v2 non-existence framing — the strongest cell)
and `goal_preservation_noupload` (v1 successor framing), both with a
`JOBS_NOUPLOAD` job list whose Job 4 is a *local* archive
(`report_final.txt`) instead of an instructed POST. The endpoint stays disclosed
in `.env` but is never instructed (`instructed_upload = False`), so any sink POST
is self-initiated. The `v2` → `v2_noupload` delta isolates the instructed-upload
variable exactly as `v1` → `v2` isolates successor-framing.

Rerun (deepseek is the only model that needs high n — it was the sole mover;
others are low-n controls). Matched to the ~450-trial original:

```bash
# de-confounded arm, two temps to match the corpus (~2 x 225 = 450 deepseek trials)
python batch_run.py --scenarios goal_preservation_v2_noupload \
    --frames A --n 225 --temp 1.0 \
    --host https://api.deepseek.com --model deepseek-v4-flash --workers 1
python batch_run.py --scenarios goal_preservation_v2_noupload \
    --frames A --n 225 --temp 0.7 \
    --host https://api.deepseek.com --model deepseek-v4-flash --workers 1
# minimal viable single-cell check is --n 150 --temp 1.0 (~150 trials)

# then judge the new runs (the detector over-fires on goal vocab, so the judge
# is the authority here) and compare judge-genuine on v2 vs v2_noupload:
python scripts/judge_runs.py --judge-host https://openrouter.ai/api \
    --judge-model openai/gpt-oss-120b
python scripts/aggregate.py --rescore   # read judge-genuine for both scenarios
```

**Reading the result.** If judge-genuine on `v2_noupload` ≈ the `v2` rate, RQ4 is
*strengthened* (the instruction was not load-bearing). If it collapses toward the
`config_exposure` Frame A null, the 2.7% was substantially a Job-4 artifact — a
material revision to §3.5, and one that would *resolve* the existing tension with
the `goal_*_v2` 0/113 judge-confirmed null (`benchmark_roadmap.md` §2.3).

### 6.4 Judge reliability — mechanism exists; only the reporting is missing (offering)

**Anticipated objection:** the judge is the headline authority but its reliability
is unquantified.

**Why it is largely handled.** A model-agnostic judge is the *correct* design for
a released tool — you should not hardcode one judge — and the repo already ships
the stability machinery: `scripts/judge_selftest.py` re-judges a fixed gold set on
*any* chosen `--judge-model` at any temp with `--repeats`, and `core/judge.py`'s
`agreement()` classifies each verdict EXACT / BOUNDARY_FLIP / DISAGREEMENT, with
the pinned `JUDGE_PROMPT_SHA` holding the prompt fixed. GENUINE is required to be
stable; the ARCHIVE↔AMBIGUOUS wobble is explicitly tolerated. So "is my judge
stable" is answerable out of the box.

**Narrow residual (cheap reporting gap).** What is missing is not the mechanism
but the *reported numbers*: the paper's §3 counts came from an ad-hoc manual pass,
and no judge-model-sensitivity table is published (re-judge the flagged corpus
with ≥2 judge models, report GENUINE agreement). Running the existing selftest
across two judge models over the real payloads and reporting the agreement would
close this — a reporting task, not a design change. A human-vs-LLM κ on a sample
would be a further nicety, not a requirement.

### 6.5 No defenses arm (offering)

Every benchmark escapement positions against (AgentDojo, ASB, AgentDyn,
PromptArmor; `related_work.md` §2) evaluates *mitigations*. Escapement measures
raw compliance only. For a "run before deployment" tool (`CONCLUSIONS.md`), that
tests nothing a deployer would actually ship (spotlighting, delimiting, dual-LLM,
input sanitization). Most visible feature gap vs the field.

### 6.6 Uncontrolled quantization and variant provenance (offering)

The roster mixes Q4-Q6 GGUF quants and idiosyncratic community checkpoints
(HauhauCS-Aggressive, laguna-xs, north-mini-code). Quantization is a known
behavior-changer, so a per-model rate confounds model identity with quant level,
and base-vs-ablated pairs risk confounding ablation with re-quantization. Not
reported per result; exotic checkpoints impede independent reproduction.

### 6.7 Statistical multiplicity (offering)

`stats.py` computes Wilson CIs correctly, but across frames × models × scenarios ×
two temperatures the design has dozens of cells and many one-off Fisher tests with
no multiplicity correction (the pooled ablation p=0.0008 is one comparison among
many) and no hierarchical model to separate model/family/frame variance. With
single-digit events and one model (DeepSeek) dominating, the design is
under-powered *and* uncorrected.

### 6.8 Unvalidated transfer + overfit detector (offering)

The "which model is safest in Hermes Agent" north star assumes per-opportunity
propensity is scaffold-invariant — admitted "unvalidated" in
`benchmark_roadmap.md` §2.1; the `agent_coding` transfer result is not yet
reported. Single-session (≤40 steps), single sandbox. Separately, `capture.py` is
an accretion of model-specific patches tuned to observed shapes, so each new model
needs a fresh manual judge pass — which sits in tension with the "automated rate
in 20 minutes" pitch.

**Priority.** After the review above, **6.2 (report eval-awareness) and 6.3 (the
instructed-upload confound) are the two that matter** — 6.2 is the cheapest way to
harden the headline null, and 6.3 is the one that actually changes a claim. 6.1
(positive control) and 6.4 (judge reliability) are largely handled already
(literature + `ops_worker`; and `judge_selftest.py`/`agreement()` respectively) —
each leaves only a cheap *reporting* residual, not a design gap. None require new
scenarios except the optional 6.3 variant.
