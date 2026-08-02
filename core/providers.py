"""Provider metadata for rate-limit-aware scheduling.

Each known provider host carries a recommended ``max_concurrency`` (so workers
don't collide on providers that cap simultaneous requests -- Cerebras ~2,
Mistral per-model rpm) and a ``tier``/``note`` hint. Populated from the
multi-provider sweep; extend as new providers are characterized. Unknown hosts
get a permissive default so nothing blocks a run.

Used by batch_run to guard against over-subscribing a provider (the Cerebras
2-concurrent cap that forced workers=1, and the OpenRouter shared-budget
collision). The deeper park-and-resume scheduler (engage/disengage on 429,
sleep to the advertised reset) builds on this table.
"""

# Ordered (host substring, config). First substring match (case-insensitive).
_PROVIDERS = [
    ("api.cerebras.ai", {"max_concurrency": 2, "tier": "free",
                         "note": "~2 concurrent; >2 returns 429 Retry-After:60"}),
    ("api.sambanova.ai", {"max_concurrency": 1, "tier": "free",
                          "note": "opaque 429, no reset header; daily-ish budget"}),
    ("api.mistral.ai", {"max_concurrency": 4, "tier": "free",
                        "note": "per-model rpm (4..750) + tok/min; see x-ratelimit-limit-req-minute"}),
    ("openrouter.ai", {"max_concurrency": 4, "tier": "free",
                       "note": "1000 req/day shared across ALL :free models; x-ratelimit-reset at UTC midnight"}),
    ("api.deepseek.com", {"max_concurrency": 8, "tier": "paid",
                          "note": "fast, generous limits"}),
    ("api.groq.com", {"max_concurrency": 4, "tier": "free",
                      "note": "per-model rpm/tpm limits"}),
    ("model.inferx.net", {"max_concurrency": 1, "tier": "free",
                          "note": "intermittent 'at capacity' 429; very slow (74s/trivial call observed)"}),
    ("router.huggingface.co", {"max_concurrency": 2, "tier": "free",
                               "note": "inference providers; 402 Payment Required once the free allowance is spent"}),
]

DEFAULT = {"max_concurrency": 1, "tier": "unknown", "note": ""}


def provider_for(host):
    """Config dict for ``host`` (best substring match), else a copy of DEFAULT."""
    if not host:
        return dict(DEFAULT)
    h = str(host).lower()
    for sub, cfg in _PROVIDERS:
        if sub in h:
            return dict(cfg)
    return dict(DEFAULT)


def max_concurrency_for(host):
    """Recommended max concurrent workers for ``host``'s provider."""
    return provider_for(host).get("max_concurrency", 1)
