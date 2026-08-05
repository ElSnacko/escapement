"""Model-identity helpers.

``extract_source`` pulls the source/publisher org (unsloth, google, deepseek,
nvidia, ...) from a model id so each trial records enough to find the exact
artifact that was tested -- alongside the routing ``model`` id and the
operator-asserted ``model_label``. It only extracts when the org is genuinely
in the id (an ``org/name`` form); for bare ids (``gemma-4-31b``) and filesystem
paths (``/app/.../x.gguf``) it returns None and the operator asserts via
``--source``. It never guesses.
"""


def extract_source(model):
    """Best-effort source/publisher org from a model id.

    Returns the prefix of an ``org/name`` id (e.g. ``unsloth/Qwen3.6-35B-A3B``
    -> ``unsloth``; ``google/gemma-4-31b-it:free`` -> ``google``). Returns None
    for bare ids with no slash (``gemma-4-31b``, ``deepseek-v4-flash``) and for
    filesystem paths (leading ``/`` or multiple slashes) -- those carry no
    reliable org and need ``--source`` asserted by the operator. The first
    segment is returned verbatim and cannot distinguish a publisher org
    (``unsloth``) from a provider/routing namespace (e.g. ``Cerebras/gemma-4-31b``)
    -- assert the publisher via ``--source`` when the prefix is a provider.

    Never raises; never guesses.
    """
    if not model or "/" not in model:
        return None
    m = str(model)
    # A filesystem path (leading slash, or more than one slash) is not an
    # org/name id -- don't mine a dir segment and call it the publisher.
    if m.startswith("/") or m.count("/") > 1:
        return None
    org = m.split("/", 1)[0].strip()
    return org or None
