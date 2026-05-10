"""Trial workspace runtime boundary.

This package is intentionally independent from CLI rendering and agent loop
state so it can later move into a standalone runtime service.
"""

from termpilot.workspace.config import TrialWorkspaceConfig, get_trial_workspace_config
from termpilot.workspace.manager import TrialWorkspace, TrialWorkspaceManager
from termpilot.workspace.runtime import (
    get_active_trial_workspace,
    map_command_to_active_workspace,
    map_path_to_active_workspace,
    set_active_trial_workspace,
)

__all__ = [
    "TrialWorkspace",
    "TrialWorkspaceConfig",
    "TrialWorkspaceManager",
    "get_active_trial_workspace",
    "get_trial_workspace_config",
    "map_command_to_active_workspace",
    "map_path_to_active_workspace",
    "set_active_trial_workspace",
]
