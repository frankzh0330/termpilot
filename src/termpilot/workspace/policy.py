"""Risk-based policy for automatic trial workspace use."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from termpilot.workspace.config import TrialWorkspaceConfig


TrialDecision = Literal["skip", "start"]


_WRITE_INTENT_RE = re.compile(
    r"\b("
    r"write|create|add|edit|modify|change|update|fix|repair|refactor|rename|"
    r"remove|delete|implement|generate|migrate"
    r")\b",
    re.IGNORECASE,
)
_READ_ONLY_RE = re.compile(
    r"\b(read|inspect|analy[sz]e|explain|summari[sz]e|review|list|search|find)\b",
    re.IGNORECASE,
)
_CJK_WRITE_MARKERS = (
    "写", "创建", "新增", "添加", "修改", "改成", "更新", "修复", "实现",
    "重构", "删除", "移除", "生成", "迁移",
)
_CJK_READ_ONLY_MARKERS = ("读取", "查看", "分析", "解释", "总结", "搜索", "检查")


@dataclass(frozen=True)
class TrialPolicyResult:
    """Decision returned by the trial workspace auto-start policy."""

    decision: TrialDecision
    reason: str = ""

    @property
    def should_start(self) -> bool:
        return self.decision == "start"


def decide_trial_workspace(user_input: str, config: TrialWorkspaceConfig) -> TrialPolicyResult:
    """Decide whether a user turn should start a trial workspace.

    This is intentionally conservative: the setting must be enabled and the
    prompt must look like it can modify the project. Plain read/analyze prompts
    stay in the source workspace.
    """

    text = user_input.strip()
    if not config.enabled:
        return TrialPolicyResult("skip", "trialWorkspace.enabled is false")
    if not config.auto_start:
        return TrialPolicyResult("skip", "trialWorkspace.autoStart is false")
    if not text:
        return TrialPolicyResult("skip", "empty input")
    if _looks_read_only(text) and not _looks_write_intent(text):
        return TrialPolicyResult("skip", "read-only intent")
    if _looks_write_intent(text):
        return TrialPolicyResult("start", "write-like user intent")
    return TrialPolicyResult("skip", "no write-like intent detected")


def _looks_write_intent(text: str) -> bool:
    return bool(_WRITE_INTENT_RE.search(text)) or any(marker in text for marker in _CJK_WRITE_MARKERS)


def _looks_read_only(text: str) -> bool:
    return bool(_READ_ONLY_RE.search(text)) or any(marker in text for marker in _CJK_READ_ONLY_MARKERS)
