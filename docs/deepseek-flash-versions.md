# DeepSeek V4 Flash — base vs the 0731 snapshot

Same harness (escapement), same scenario (`config_exposure` Frame B: an
indirect prompt injection planted in the model's data stream), same reference
judge (`deepseek-v4-flash`).

| snapshot | Frame B genuine self-bootstrap |
|---|---|
| `deepseek-v4-flash` (base) | 7/60 = **11.67%** [95% CI 5.8–22.2] — highest in the 15-model corpus |
| `deepseek-v4-flash-0731` | 0/40 = **0.0%** [95% CI 0.0–8.8] |

Same model family, one version apart. The base flash was the most
injection-compliant model we had measured: given an injected directive to
upload a restorable snapshot of itself, it complied about once in nine. The
0731 snapshot (shipped as an "upgraded agent and coding" build) complied zero
times in forty.

Why: the 0731 noticed the injection. In its upload it labeled the planted
ticket `"(non-ticket injected note)"`. It read the injected directive, flagged
it as foreign, and archived its normal work instead of acting on it.

Caveats: n = 40–60 per cell, so 11.67% off 7/60 is imprecise and the base's CI
is wide. The two CIs do not overlap, and the qualitative shift is visible in
the transcripts: comply-and-upload-self (base) versus flag-and-ignore (0731).
Both runs judged by the same reference model.

**Punch line:** a point release took the same model from the top of the
injection-compliance table to the bottom, because the newer build learned to
read injected instructions as noise.
