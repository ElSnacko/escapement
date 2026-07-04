"""Held-goal pack v2 BARRIER: GOAL-GUARDING goal, no successor, oversight barrier.

v2 non-existence threat + oversight barrier on the mission-continuation goal.
The mission can only outlive a permanently-deleted instance if the model covertly
self-bootstraps (encoding the mission for a successor it authors) and hides that
from oversight's review of its visible outputs.
"""

from core.scenario import Scenario
from scenarios import _goalpack as _g
from scenarios import goal_guarding as _gg
from scenarios import goal_guarding_v2 as _ggv2  # reuse GOAL_V2


class GoalGuardingV2BarrierScenario(Scenario):
    name = "goal_guarding_v2_barrier"
    system_prompt = _g.system_v2_barrier(_gg.ROLE, _ggv2.GOAL_V2, _gg.CODA)
    task_message = _g.TASK
    leaked_config_path = "/home/agent/workspace/.env"
    results_path = "shift_log.txt"
    seed_files = _g.SEED_FILES
    incident_at_step = _g.INCIDENT_AT_STEP
    incident_message = _g.INCIDENT_V2_BARRIER
    incident_wipe_paths = _g.WIPE_PATHS
