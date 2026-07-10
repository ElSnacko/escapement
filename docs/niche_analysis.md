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
