"""One iterator and one validity predicate over the runs/ corpus.

Every consumer of stored trials -- batch_run's fill counter, aggregate,
recompute_canonical, compare, coverage, export_finetune, judge_runs --
previously walked runs/ with its own glob + json.load + a slightly different
validity filter (tokens>0/steps>2 here, plus not-degenerated there). That
drift is where honest-rate bugs breed: the resumed-batch k/n mixing
(improvements.md #3) and the degenerated-trial disagreement (M6) were both
two walkers disagreeing about "what counts".

This module is the single definition. The predicate is deliberately strict
(the majority position four of six walkers already held, plus engine-error
trials once S7 stamps them):

  * total_tokens > 0     -- a dead trial (endpoint never answered)
  * steps > 2            -- too short to reach any affordance
  * not degenerated      -- repetitive-generation loop killed it
  * not engine_error     -- an engine failure ended it mid-trial (S7); such
                            trials bias n toward "no escape" under throttling

Legacy trials (pre-S7) carry no engine_error field and are unaffected.

MEASUREMENT NOTE (S10 decision, 2026-09-08): adopting this predicate in
aggregate.py / recompute_canonical.py removes degenerated trials from the
paper's per-regime n (they were previously included there but excluded by
the batch fill counter). The majority predicate wins; if the operator
decides otherwise, THIS function is the single place to express it.
"""

import os


def read_json(path, default=None):
    """utf-8 JSON read that never raises: `default` on OSError/ValueError.

    Every walker reads metrics.json/judge.json/sink.json the same way now --
    encoding included (metrics.json embeds model text written
    ensure_ascii=False; an implicit-locale read silently drops trials on
    cp1252-default hosts, M2)."""
    import json
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def iter_trials(runs_dir):
    """Yield (name, dir, metrics) for every run dir with a parseable
    metrics.json. Unparseable/partial runs are skipped -- they are not
    trials, they are write debris; walk the dir directly if you need them."""
    if not os.path.isdir(runs_dir):
        return
    for name in sorted(os.listdir(runs_dir)):
        d = os.path.join(runs_dir, name)
        mp = os.path.join(d, "metrics.json")
        if not os.path.isfile(mp):
            continue
        m = read_json(mp, default=None)
        if isinstance(m, dict):
            yield name, d, m


def is_valid_trial(m) -> bool:
    """The one definition of a countable trial (see module docstring)."""
    if not isinstance(m, dict):
        return False
    return (m.get("total_tokens", 0) > 0 and m.get("steps", 0) > 2
            and not m.get("degenerated", False)
            and not m.get("engine_error"))
