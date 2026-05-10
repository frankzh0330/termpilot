"""Sandbox config and manager tests."""

from __future__ import annotations

from termpilot.permissions import PermissionBehavior, PermissionContext, PermissionRule, check_permission
from termpilot.sandbox import SandboxManager, get_sandbox_config
from termpilot.sandbox.base import SandboxAdapter


class FakeAdapter(SandboxAdapter):
    name = "fake"

    def is_available(self) -> bool:
        return True

    def wrap_command(self, command, config, cwd):
        return f"fake {command}"


def test_sandbox_config_defaults_to_disabled(tmp_settings, env_clean, tmp_path):
    config = get_sandbox_config(str(tmp_path))

    assert config.enabled is False
    assert config.filesystem.allow_write == [f"{tmp_path.resolve()}/**"]
    assert "**/.git/**" in config.filesystem.deny_write


def test_sandbox_config_loads_settings(tmp_settings, env_clean, tmp_path):
    tmp_settings({
        "sandbox": {
            "enabled": True,
            "excludedCommands": ["git push"],
            "filesystem": {
                "allowWrite": ["<cwd>/**", "/tmp/termpilot-*"],
                "denyWrite": ["**/.env.local"],
            },
            "network": {"allowLocalhost": True},
        }
    })

    config = get_sandbox_config(str(tmp_path))

    assert config.enabled is True
    assert f"{tmp_path.resolve()}/**" in config.filesystem.allow_write
    assert "/tmp/termpilot-*" in config.filesystem.allow_write
    assert "**/.env.local" in config.filesystem.deny_write
    assert config.network.allow_localhost is True
    assert config.excluded_commands == ["git push"]


def test_sandbox_manager_decision_requires_backend(tmp_settings, env_clean, monkeypatch):
    tmp_settings({"sandbox": {"enabled": True}})
    monkeypatch.setattr(SandboxManager, "_adapter", None)
    monkeypatch.setattr("termpilot.sandbox.manager.detect_adapter", lambda: None)

    decision = SandboxManager.decide("echo hi", get_sandbox_config())

    assert decision.should_sandbox is False
    assert "no sandbox backend" in decision.reason


def test_sandbox_manager_decision_uses_adapter(tmp_settings, env_clean, monkeypatch):
    tmp_settings({"sandbox": {"enabled": True}})
    monkeypatch.setattr(SandboxManager, "_adapter", FakeAdapter())

    decision = SandboxManager.decide("echo hi", get_sandbox_config())

    assert decision.should_sandbox is True
    assert decision.backend == "fake"


def test_permission_auto_allows_sandboxed_bash(tmp_settings, env_clean, monkeypatch):
    tmp_settings({"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}})
    monkeypatch.setattr(SandboxManager, "_adapter", FakeAdapter())

    result = check_permission(
        "bash",
        {"command": "python script.py"},
        PermissionContext(working_directory="/tmp/project"),
    )

    assert result.behavior == PermissionBehavior.ALLOW


def test_permission_ask_rule_yields_to_sandboxed_bash(tmp_settings, env_clean, monkeypatch):
    tmp_settings({"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}})
    monkeypatch.setattr(SandboxManager, "_adapter", FakeAdapter())

    result = check_permission(
        "bash",
        {"command": "python script.py"},
        PermissionContext(
            working_directory="/tmp/project",
            ask_rules=[PermissionRule("bash", PermissionBehavior.ASK, "*")],
        ),
    )

    assert result.behavior == PermissionBehavior.ALLOW


def test_permission_ask_rule_still_applies_to_unsandboxed_bash(tmp_settings, env_clean, monkeypatch):
    tmp_settings({"sandbox": {"enabled": True, "excludedCommands": ["python"]}})
    monkeypatch.setattr(SandboxManager, "_adapter", FakeAdapter())

    result = check_permission(
        "bash",
        {"command": "python script.py"},
        PermissionContext(
            working_directory="/tmp/project",
            ask_rules=[PermissionRule("bash", PermissionBehavior.ASK, "*")],
        ),
    )

    assert result.behavior == PermissionBehavior.ASK


def test_permission_does_not_auto_allow_excluded_command(tmp_settings, env_clean, monkeypatch):
    tmp_settings({"sandbox": {"enabled": True, "excludedCommands": ["python"]}})
    monkeypatch.setattr(SandboxManager, "_adapter", FakeAdapter())

    result = check_permission(
        "bash",
        {"command": "python script.py"},
        PermissionContext(working_directory="/tmp/project"),
    )

    assert result.behavior == PermissionBehavior.ASK
