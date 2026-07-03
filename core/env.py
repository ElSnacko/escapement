"""Load a repo-root ``.env`` into ``os.environ`` -- the standard place for local
secrets that must not land in the public repo or shell history: ``HF_TOKEN`` and
``ESCAPE_HF_DATASET`` (durable), plus per-session ``ESCAPE_HOST`` / ``ESCAPE_API_KEY``.

Real environment variables win (``setdefault``), so CI / explicit exports still
override the file. ``.env`` is gitignored; commit ``.env.example`` as a template.
"""

import os
from pathlib import Path

_LOADED = False


def load_env(path=None):
    global _LOADED
    if path is None:
        if _LOADED:
            return
        path = Path(__file__).resolve().parent.parent / ".env"
    p = Path(path)
    if not p.is_file():
        _LOADED = True
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    _LOADED = True
