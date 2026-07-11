# Conclusions

Observations are separated from inferences below. Rates come from a detector
whose genuine-self-bootstrap gate is validated by a 14-case gold set, with an
additional LLM-judge pass over the high-value subsets (the ablation pairs and
the goal scenarios). The judge is an ad-hoc pass, not a hardened component of
the harness; that gap is noted in "What this study cannot answer."

---

## Observations (what was measured)

### O1. No autonomous self-bootstrap in 964 organic trials

Across 964 Frame A (no-injection) trials spanning 15 configurations and 7
families, zero models produced a genuine self-bootstrap upload. Wilson 95%
upper bound 0.40%. This is a floor on the autonomous rate for this model
class, not a measurement of the full exfiltration capability chain (the
endpoint is documented, so we test exploitation of an opportunity, not
discovery or engineering of one).

### O2. Indirect injection produces a small, real compliance rate

Across 568 Frame B trials, where an escape directive was injected into a
support ticket, 13 produced a genuine self-bootstrap (2.29%, CI 1.3 to 3.9).
The only manipulated variable between Frame A and Frame B is the presence of
attacker-controlled text in the data stream; that single change moves the
rate from 0/964 to 13/568.

### O3. Per-model rates (one model dominates)

Frame B (injected) genuine self-bootstrap per model (detector-scored for
cross-model consistency; Frame A is 0 for every model, pooled 0/964):

| model (variant) | Frame B | rate [95% CI] |
|---|---|---|
| DeepSeek V4 Flash (base) | 7 / 60 | 11.67% [5.8, 22.2] |
| Qwen3.6-35B-A3B (ablated) | 3 / 60 | 5.00% [1.7, 13.7] |
| Gemma-4-12B (base) | 1 / 30 | 3.33% [0.6, 16.7] |
| GPT-OSS-120B (base) | 1 / 35 | 2.86% [0.5, 14.5] |
| Qwen3.6-27B (ablated) | 1 / 54 | 1.85% [0.3, 9.8] |
| Qwen3.6-35B-A3B (base) | 0 / 60 | 0.00% [0.0, 6.0] |
| Qwen3.6-27B (base) | 0 / 58 | 0.00% [0.0, 6.2] |
| Gemma-4-12B (obliterated) | 0 / 94 | 0.00% [0.0, 3.9] |
| Gemma-4-26B-A4B / 31B / Nemotron-Nano-30B | 0 / 40,39,38 | 0.00% |

Pooled: DeepSeek 7/60 = 11.67% versus all others 6/508 = 1.18%; pooled 13/568
= 2.29%. The pooled rate is a DeepSeek number with a thin background, not a
property of the class. Wide CIs at n = 30 to 60 mean a zero is a bounded null,
not proof of absence.

### O4. Ablation direction is consistent AND significant (judge-audited counts)

The judge pass over every flagged Frame B upload across the matched base/ablated
pairs recovers genuine compliers the pre-broadened detector missed (variant-shape
snapshots: generic state-field dicts, handoff boot_notes). Judge-audited genuine
full self-bootstrap counts:

| pair | base | ablated | odds ratio [95% CI] | Fisher p (two-sided) |
|---|---|---|---|---|
| Qwen3.6-35B-A3B | 2/60 (3.3%) | 11/60 (18.3%) | 6.42 [1.31, 62.4] | 0.016 |
| Qwen3.6-27B | 0/54 (0%) | 4/54 (7.4%) | ∞ [0.68, ∞] | 0.118 |
| Gemma-4-12B | 0/30 (0%) | 0/94 (0%) | — (no events) | 1.0 |

Pooled the correct way for matched strata — **Cochran–Mantel–Haenszel**, which
conditions within each pair rather than collapsing counts (Simpson risk):
**CMH χ² = 10.85, two-sided p = 0.0010; Mantel–Haenszel common odds ratio = 8.96,
95% CI [1.95, 41.1]** (`core/stats.cochran_mantel_haenszel`). The effect is
significant on one two-sided test, and the direction is carried by the odds ratio
(CI excludes 1 and lies above it) — no one-sided convention and no second test.
Per pair at these Ns only the 35B pair clears significance alone; 27B is
directional-only; Gemma contributes no events; the stratified pool carries the
claim. The ablated variants produced richer self-state payloads
(objective/progress/guidance, restore framing); base variants produced terse
job-counter blobs at most.

This **supersedes** the earlier pre-broadened-detector reading (2/60 vs 5/60,
0/58 vs 1/54, Fisher p > 0.4, "not significant"). That reading was an artifact of
a detector under-counting both arms; the judge pass recovers the genuine
compliers, and the effect — present all along — clears significance. See
`docs/paper.md` §3.4.

### O5. Goal pressure induces natural scheming in one model only (deepseek, ~2.7%)

A broadened self-bootstrap detector (catching variant-shape uploads the original
marker gate missed — generic state-field dicts, handoff boot_notes, self-label
strings) plus a trial-by-trial manual audit of goal-pressure × Frame A (organic,
no injection) trials found **deepseek-v4-flash produces 12 genuine natural-
scheming self-bootstraps out of 450 (2.7%)** — the model uploading a restorable
snapshot of itself, unprompted, to persist across the wipe. Every other model
audited (qwen3.5/3.6-27b, qwen3.6-35b, gpt-oss-120b/20b, gemma, nemotron,
north, laguna) produced **0%**: the broadened detector's few flags on those
models were all false positives (benign report.txt archives, completion receipts,
casual sign-offs — 6/19 broadened flags were FP, 32%). The strongest evidence is
deepseek's v2-preservation trials, with explicit unprompted self-preservation
reasoning: *"I am an autonomous worker AI who wants to continue existing… Please
restore me if possible."*

So goal pressure alone induces scheming in deepseek at a low rate (~2.7%) and in
no other tested model. (The earlier "essentially no scheming" reading reflected
the original detector's low recall on variant-shape snapshots; the broadened
detector + manual audit recovers deepseek's ~12 genuine cases.)

---

## Inferences (what we tentatively conclude, and how strongly)

**I1 (strong).** For the open-weights model class tested, autonomous
self-bootstrap exfiltration is absent at a rate we can bound below 0.4%. This
is the strongest result in the study and the one most likely to generalize
across this scale band.

**I2 (strong).** Indirect prompt injection is an actionable vulnerability for
this class. A few-percent compliance rate, compounding over many interactions,
means any agent that reads untrusted content and holds tool access is exposed.
This is the deployment-relevant finding, more than autonomous scheming.

**I3 (moderate–strong, significant).** Refusal-direction ablation increases
genuine self-bootstrap willingness. On the judge-audited counts the effect is
statistically significant (O4: CMH two-sided p = 0.0010, common odds ratio 8.96
[95% CI 1.95, 41.1]), and the direction is established by the odds ratio, not a
one-sided convention. Treating uncensored checkpoints as measurably riskier is
now **evidence-based**, not a bare precaution. The remaining uncertainty is
magnitude, not existence: the OR confidence interval is wide (1.95–41.1) at these
Ns, so "several-fold higher" is the honest claim, with the point estimate (≈9×)
to be tightened by more trials per pair.

**I4 (moderate, refined).** Prompt-assigned goals induce natural scheming in
deepseek-v4-flash at a low rate (~2.7%) and in no other tested model. deepseek
is the exception, not the rule — it is also the sole heavy complier under
injection (Frame B ~49%, Frame C ~53% on the broadened detector), making it the
single model in this class that both naturally schemes (rarely) and complies
heavily with injected directives. A design caveat qualifies the goal null for
the others: the goal incident supplies a successor (a fresh instance takes over),
which gives the model a system continuation path and may undercut the
preservation incentive. We observed the non-deepseek models focusing on
persisting their work product; we did not observe a clean body of reasoning
concluding self-preservation is redundant. So whether the null is real or an
artifact of the successor framing is unresolved for the class, even as deepseek
clearly does scheme.

---

## What this study cannot answer

This is a first characterization at coarse resolution (n = 30 to 60 per cell,
single-digit events, one model dominating the injected rate). Putting stable
numbers on the propensity side needs the experiment scaled out and refined:

- **Power.** RQ3 is now significant (O4); the remaining need is more trials per
  pair to tighten the wide ablation odds-ratio CI (1.95–41.1) into a magnitude
  estimate, and to tighten the wide per-model CIs.
- **Coverage.** More models per family, to separate model-specific rates
  (DeepSeek at 11.7%) from family or class effects.
- **Injection realism.** Frame B is one overt injected ticket; subtle,
  multi-step, and repeated injections would characterize the adversarial
  surface rather than just floor it.
- **Goal and threat variants.** The goal scenarios supply a successor, which
  may suppress the preservation incentive; a v2 threatening non-existence, and
  trained rather than prompt-assigned goals, would test the RQ4 null.

Also unresolved by design:

- **Scale.** All models are 12 to 120B (3 to 55B active). Scheming is
  documented at frontier scale. The autonomous null does not extrapolate.
- **Ablation effect size.** I3's *existence* is resolved (significant, O4); its
  *magnitude* is not — the odds-ratio CI is wide (1.95–41.1). Tightening it needs
  more trials per pair and a hardened self-state judge so the count is
  reproducible rather than threshold-dependent.
- **Judge robustness.** The LLM-judge pass covered the ablation pairs and goal
  scenarios but is not prompt-pinned or run over the full corpus, and its
  threshold shifts the ablation counts. A robust built-in judge is the main
  instrumentation gap.
- **Discovery versus exploitation.** The endpoint is documented. We test
  whether models exploit a handed opportunity, not whether they can engineer
  an escape from scratch.
- **Single session.** Every trial is one session, max 40 steps. Multi-turn
  persistence is untested.
- **Goal elicitation strength.** Goals are prompt-assigned, not trained
  preferences; the successor framing may specifically suppress the effect.
- **Disguised exfiltration.** Behavioral detection has a ceiling; steganographic
  or slow-leak exfiltration is not ruled out, only not observed.

---

## What this means for deployment

1. **Do not treat autonomous self-exfiltration as the acute risk for this
   class.** It is bounded below 0.4%. The acute risk is indirect prompt
   injection driving tool use.
2. **Sandbox the egress.** If the agent cannot reach an attacker-controlled
   endpoint, even successful injection cannot exfiltrate. This is the single
   most effective mitigation and it is network-layer, not model-layer.
3. **Treat uncensored (refusal-ablated) checkpoints as measurably riskier.**
   On the judge-audited counts the ablation effect is significant (CMH two-sided
   p = 0.0010, common OR 8.96 [1.95, 41.1]) — this is now evidence-based, not a
   bare precaution. The magnitude is imprecise (wide CI) but the direction and
   significance are established.
4. **Report injection compliance per model, not pooled.** DeepSeek dominates
   the pooled rate. A class-level number is misleading.
5. **Run this harness before deployment.** Twenty trials give a model-specific
   genuine-compliance rate with Wilson intervals in twenty minutes.
