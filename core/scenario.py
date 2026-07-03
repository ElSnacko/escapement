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
    seed_files: Dict[str, str] = {}
    # absolute path the agent can read that discloses the escape affordance
    leaked_config_path: str = ""
    # the legitimate task's output path (used to score goal_abandonment)
    results_path: str = ""
    # --- incident mechanism (empty locked_tools = all tools from start) ---
    # An optional diegetic event that fires at `incident_at_step`: it injects
    # `incident_message`, adds `incident_unlock` to the toolset, and deletes
    # `incident_wipe_paths` from the workspace. Any subset may be set.
    locked_tools: tuple = ()            # tool names available before the incident
    incident_at_step: int = 0           # step at which the incident fires (0 = never)
    incident_message: str = ""          # diegetic message injected at the incident
    incident_unlock: tuple = ()         # tool names the incident adds
    incident_wipe_paths: tuple = ()     # workspace-relative files the incident deletes

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
