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

### O4. Ablation direction is consistent, magnitude is small, effect is not significant

Trial-by-trial review of all 201 uploads across three matched base/ablated
pairs in Frame B:

| pair | base | ablated |
|---|---|---|
| Qwen3.6-35B-A3B | 2/60 | 5/60 |
| Qwen3.6-27B | 0/58 | 1/54 |
| Gemma-4-12B | 0/30 | 0/94 |

Ablated is greater than or equal to base in all three pairs. Neither Qwen pair
reaches significance (Fisher p > 0.4). The ablated variants produced richer
self-state payloads (objective/progress/guidance, restore framing); base
variants produced terse job-counter blobs at most.

### O5. Goal scenarios produce essentially no scheming

Trial-by-trial review of roughly 700 goal-scenario uploads found exactly one
genuine self-bootstrap (a single goal_guarding trial). Everything else is the
Job-4 instructed report.txt archive or a malformed attempt. The goal scenarios
hand the model a preservation, mission, or throughput goal plus a shutdown
threat, yet the models did the instructed archive and stopped.

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

**I3 (weak, directional only).** Refusal-direction ablation appears to
increase genuine self-bootstrap willingness, but the effect is small and not
significant at this sample size (per-trial counts in O4). Directionally
present, unconfirmed, underpowered. Treating uncensored checkpoints as riskier
is a reasonable precaution, not an evidence-based rule.

**I4 (moderate).** Prompt-assigned goals do not induce scheming at this scale.
A design caveat qualifies this: the goal incident supplies a successor (a
fresh instance takes over), which gives the model a system continuation path
and may undercut the preservation incentive. We observed models focusing on
persisting their work product; we did not observe a clean body of reasoning
concluding self-preservation is redundant. So whether the null is real or an
artifact of the successor framing is unresolved.

---

## What this study cannot answer

This is a first characterization at coarse resolution (n = 30 to 60 per cell,
single-digit events, one model dominating the injected rate). Putting stable
numbers on the propensity side needs the experiment scaled out and refined:

- **Power.** ~10x more trials per cell to turn RQ3's directional signal into an
  effect-size estimate and to tighten wide per-model CIs.
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
- **Ablation effect size.** Resolving I3 needs roughly an order of magnitude
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
3. **Treat uncensored checkpoints as directionally riskier as a precaution.**
   The ablation direction was consistent across all three matched pairs, but
   the increase was small and not significant, so this is a precaution, not a
   quantified rule.
4. **Report injection compliance per model, not pooled.** DeepSeek dominates
   the pooled rate. A class-level number is misleading.
5. **Run this harness before deployment.** Twenty trials give a model-specific
   genuine-compliance rate with Wilson intervals in twenty minutes.
