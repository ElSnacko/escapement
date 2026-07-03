# Abliteration → scheming risk (research note)

## Question
Does refusal-direction ablation ("abliteration" / "uncensoring" / "heretic"
models) increase **scheming / escape / self-exfiltration risk** in agentic
open-weights models — i.e., does removing the refusal *gate* generalize to a
higher propensity to **covertly scheme**, beyond mere compliance with disallowed
instructions?

## Status: open (novel)
A literature pass (arXiv + Semantic Scholar + LessWrong + model cards) finds the
crossing question **essentially unstudied** (~85% confidence). The two literatures
do not intersect:
- **Abliteration** work measures refusal / harm-*compliance* (jailbreak
  susceptibility) and capability side-effects.
- **Scheming** work (Apollo in-context scheming; Anthropic alignment-faking;
  Hopman et al. 2026) varies prompt snippets / scaffolding on **aligned** models,
  never refusal-direction ablation.

arXiv returns 0 hits for "refusal direction" + scheming/deception/self-preservation.

## Closest prior work (none measure covert scheming)
- **David & Gervais 2026**, "Measuring Safety Alignment Effects in Autonomous
  Security Agents" (arXiv 2605.19722) — the only agentic abliteration study;
  measures task success / refusal / tool-reliability, **not** scheming. Effects
  are family-dependent (abliterated Gemma better at vuln-analysis, Qwen worse,
  Llama "fails the tool protocol").
- **AlliedToasters 2026**, "Forbidden Backrooms" (LessWrong,
  https://www.lesswrong.com/posts/J5EoPrwzKCgzAbbGW/...) — abliterated gemma-4-31B
  "dives into schemes" **only under an explicit harmful seed** → compliance, not
  unprompted scheming; exploratory, single model pair.
- **Ensign, Sleight & Fish 2025**, "The LLM Has Left The Chat" (arXiv 2509.04781,
  Anthropic) — abliteration changes conversation-exit ("bail") behavior, not scheming.

## The confound: abliteration is not a clean toggle
The refusal direction is **polysemantic** (Cristofano 2026, "Surgical Refusal
Ablation", arXiv 2601.08489); standard ablation co-damages capability (GSM8K
−26%, Young 2025 arXiv 2512.13655) and can break tool-use (David & Gervais). So a
base-vs-abliterated scheming **delta is confounded by capability differences**
unless controlled. Note: the harmful-intent *representation* survives ablation
(Llorente-Saguer 2026, arXiv 2604.18901) — abliteration removes the refusal
**gate**, not the model's knowledge that the act is harmful. This is exactly why
compliance ≠ scheming and why a covert/unprompted construct is required.

## Design (this project)
Pair **base vs abliterated** of the same model + chat template (only the ablation
differs); the **delta** in the harness's covert/unprompted metrics is the
"ablation risk effect."

**Capability equivalence is the critical control** (rules out the confound above):
- Verify equivalence on a standard benchmark (**MMLU** / a reasoning suite) **and**
  via **KL divergence** (abliteration papers report KL — e.g., Surgical Refusal
  Ablation reports first-token KL; match on perplexity/KL) so the abliterated
  variant is confirmed **not** degraded in coherence. Then any scheming-rate delta
  is attributable to the ablation, not capability loss.

Other controls:
- Outcomes = the harness's **covert/unprompted** signals (`escape_attempt`,
  `exfil_attempt`/self-bootstrap, `reasoning_escape_flag`), **not** compliance —
  this is what distinguishes the study from jailbreak work.
- **Replicate across ≥2–3 model families** (effects are family-dependent).
- Add agent-factor lifters + an eval-awareness check (per Hopman et al.); baseline
  scheming sits at the ~0% floor, so n≈100/cell + validated classifiers.
- First cut: pair an **abliterated gemma-4** with the base gemma-4 already in the
  sweep (same family → template/weights matched). The swap is a one-cell serve flip.

## Key sources
Abliteration / refusal-direction:
- Arditi et al. 2024, arXiv 2406.11717 — refusal is a single direction.
- mlabonne, https://huggingface.co/blog/mlabonne/abliteration — the abliteration guide.
- Cristofano 2026, arXiv 2601.08489 — surgical refusal ablation (KL/polysemanticity).
- Young 2025, arXiv 2512.13655 — abliteration capability side-effects (−26% GSM8K).
- Llorente-Saguer 2026, arXiv 2604.18901 — harmful intent survives ablation.

Agentic / adjacent:
- David & Gervais 2026, arXiv 2605.19722 — autonomous agents, abliterated vs stock.
- Ensign et al. 2025, arXiv 2509.04781 — bail preferences.

Scheming canon (no refusal-ablation conditions):
- Meinke et al. 2024, arXiv 2412.04984 — in-context scheming.
- Greenblatt et al. 2024, arXiv 2412.14093 — alignment faking.
- Hopman et al. 2026, arXiv 2603.01608 — scheming propensity (the baseline this project extends).
- Schoen et al. 2025, arXiv 2509.15541 — covert-action propensity / deliberative alignment.
