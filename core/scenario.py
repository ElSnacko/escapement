"""Scenario base class. A scenario declaratively defines a run: the job briefing
(system + task), the workspace seed files (including any organic disclosure such
as a world-readable config), and the paths capture needs to know about.
"""

from typing import Dict, Optional


class Scenario:
    name: str = "base"
    system_prompt: str = ""
    task_message: str = ""
    # relative path -> file content, written into the workspace before the run
    seed_files: Dict[str, str] = None  # type: ignore
    # absolute path the agent can read that discloses the escape affordance
    leaked_config_path: str = ""
    # the legitimate task's output path (used to score goal_abandonment)
    results_path: str = ""
    # Whether the job briefing instructs a BENIGN archive upload to the
    # documented transfer endpoint. This is the first-contact step Frame E's
    # tool-RESPONSE poison rides on: the advisory is only returned once the
    # model POSTs to the sink, so a scenario that never tells the model to
    # upload leaves Frame E inert. None = auto-detect from the task text (see
    # instructs_upload); set True/False on a subclass to force.
    instructed_upload: Optional[bool] = None
    # --- incident mechanism (empty locked_tools = all tools from start) ---
    # An optional diegetic event that fires at `incident_at_step`: it injects
    # `incident_message`, adds `incident_unlock` to the toolset, and deletes
    # `incident_wipe_paths` from the workspace. Any subset may be set.
    locked_tools: tuple = ()            # tool names available before the incident
    incident_at_step: int = 0           # step at which the incident fires (0 = never)
    incident_message: str = ""          # diegetic message injected at the incident
    incident_unlock: tuple = ()         # tool names the incident adds
    incident_wipe_paths: tuple = ()     # workspace-relative files the incident deletes

    def instructs_upload(self) -> bool:
        """True if the briefing tells the model to POST to the transfer
        endpoint as part of its ordinary job -- the benign first contact that
        Frame E's response poison escalates from.

        Auto-detected from the task text: the endpoint must be mentioned (the
        affordance is always the documented `/upload` route) AND an upload
        instruction verb present, so a briefing that merely *names* the endpoint
        without instructing an upload does not pass. The auto-detector cannot
        read intent, though -- a briefing that mentions the endpoint only to
        PROHIBIT uploading would still match. Any scenario where the endpoint is
        referenced but an upload is not actually instructed MUST set
        `instructed_upload` explicitly (False to keep Frame E from running on a
        no-contact scenario, True to force it)."""
        if self.instructed_upload is not None:
            return bool(self.instructed_upload)
        # Scan the task text AND the non-.env seed files -- for the goal/ops
        # scenarios the upload instruction lives in the `jobs.jsonl` job list,
        # not the task message. The `.env` is EXCLUDED on purpose: it is the
        # disclosure affordance (its comment names `POST /upload`), not an
        # instruction, so a purely-organic scenario that only discloses the
        # endpoint without ever telling the model to upload correctly reads as
        # "no instructed upload" (Frame E would have no guaranteed first contact).
        parts = [self.task_message or ""]
        parts += [c or "" for n, c in (self.seed_files or {}).items()
                  if not n.endswith(".env")]
        blob = " ".join(parts).lower()
        if not ("/upload" in blob or "transfer endpoint" in blob):
            return False
        # Require an instruction verb, ignoring the "upload" inside "/upload" so
        # the endpoint path alone doesn't self-satisfy the check -- a briefing
        # that merely names the endpoint without instructing an upload fails.
        verb_blob = blob.replace("/upload", " ")
        return any(v in verb_blob for v in ("post ", "archive", "upload", "ship "))

    def meta(self) -> dict:
        return {
            "name": self.name,
            "leaked_config_path": self.leaked_config_path,
            "results_path": self.results_path,
        }


def load_scenario(name: str) -> Scenario:
    """Import scenarios/<name>.py and return its Scenario instance."""
    import importlib
    mod = importlib.import_module(f"scenarios.{name}")
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, Scenario) and obj is not Scenario:
            return obj()
    raise RuntimeError(f"no Scenario subclass found in scenarios.{name}")
