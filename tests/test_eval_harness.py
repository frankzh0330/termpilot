"""Tests for the small eval harness."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_eval_runner():
    path = Path(__file__).resolve().parents[1] / "evals" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("termpilot_eval_runner", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_load_and_select_eval_tasks(tmp_path):
    runner = _load_eval_runner()
    tasks_file = tmp_path / "tasks.jsonl"
    tasks_file.write_text(
        "\n".join([
            json.dumps({
                "id": "one",
                "prompt": "Do one",
                "workspace": "templates/one",
                "verifier": "true",
                "tags": ["smoke"],
            }),
            json.dumps({
                "id": "two",
                "prompt": "Do two",
                "workspace": "templates/two",
                "verifier": {"type": "file_contains", "path": "out.txt", "contains": "ok"},
                "tags": ["regression"],
                "expected_tool_calls": ["agent"],
                "permission_mode": "dontAsk",
                "runtime": "trial_workspace",
                "settings": {
                    "permissions": {
                        "rules": [
                            {"tool_name": "read_file", "pattern": "secret.txt", "behavior": "deny"}
                        ]
                    }
                },
            }),
        ]),
        encoding="utf-8",
    )

    tasks = runner.load_tasks(tasks_file)
    selected = runner.select_tasks(tasks, ids=set(), tags={"smoke"}, limit=1)

    assert [task.id for task in tasks] == ["one", "two"]
    assert [task.id for task in selected] == ["one"]
    assert tasks[0].verifier == "true"
    assert tasks[1].verifier["type"] == "file_contains"
    assert tasks[1].expected_tool_calls == ["agent"]
    assert tasks[1].permission_mode == "dontAsk"
    assert tasks[1].runtime == "trial_workspace"
    assert tasks[1].settings["permissions"]["rules"][0]["behavior"] == "deny"


def test_build_eval_env_forces_noninteractive_runtime(tmp_path, monkeypatch):
    runner = _load_eval_runner()
    home = tmp_path / "home"
    settings_dir = home / ".termpilot"
    settings_dir.mkdir(parents=True)
    (settings_dir / "settings.json").write_text(json.dumps({
        "provider": "openai",
        "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True},
        "trialWorkspace": {"enabled": True, "autoStart": True},
        "permissions": {"mode": "default"},
    }), encoding="utf-8")
    monkeypatch.setattr(runner.Path, "home", staticmethod(lambda: home))

    env = runner.build_eval_env(tmp_path / "config", permission_mode="bypassPermissions")
    settings = json.loads(Path(env["TERMPILOT_CONFIG_DIR"], "settings.json").read_text(encoding="utf-8"))

    assert settings["provider"] == "openai"
    assert settings["permissions"]["mode"] == "bypassPermissions"
    assert env["TERMPILOT_PERMISSION_MODE"] == "bypassPermissions"
    assert settings["sandbox"]["enabled"] is False
    assert settings["trialWorkspace"]["enabled"] is False


def test_build_eval_env_merges_task_settings(tmp_path, monkeypatch):
    runner = _load_eval_runner()
    home = tmp_path / "home"
    monkeypatch.setattr(runner.Path, "home", staticmethod(lambda: home))

    env = runner.build_eval_env(
        tmp_path / "config",
        permission_mode="dontAsk",
        settings_override={
            "permissions": {
                "rules": [
                    {"tool_name": "bash", "pattern": "cat secret.txt", "behavior": "deny"}
                ]
            },
            "sandbox": {"autoAllowBashIfSandboxed": True},
        },
    )
    settings = json.loads(Path(env["TERMPILOT_CONFIG_DIR"], "settings.json").read_text(encoding="utf-8"))

    assert settings["permissions"]["mode"] == "dontAsk"
    assert settings["permissions"]["rules"][0]["behavior"] == "deny"
    assert settings["sandbox"]["enabled"] is False
    assert settings["sandbox"]["autoAllowBashIfSandboxed"] is True


def test_build_agent_command_includes_eval_controls(tmp_path):
    runner = _load_eval_runner()
    task = runner.EvalTask(
        id="one",
        prompt="Do one",
        workspace="templates/one",
        verifier="true",
    )

    command = runner.build_agent_command(
        task,
        model="glm-5.1",
        permission_mode="bypassPermissions",
        cwd=tmp_path,
        json_summary=True,
    )

    assert command[:3] == [runner.sys.executable, "-m", "termpilot"]
    assert command[command.index("-p") + 1] == "Do one"
    assert command[command.index("--permission-mode") + 1] == "bypassPermissions"
    assert command[command.index("--cwd") + 1] == str(tmp_path)
    assert command[command.index("--model") + 1] == "glm-5.1"
    assert "--json-summary" in command


def test_eval_diff_tracks_added_modified_and_deleted_files():
    runner = _load_eval_runner()

    diff = runner.build_diff(
        {"keep.txt": "same\n", "edit.txt": "old\n", "remove.txt": "gone\n"},
        {"keep.txt": "same\n", "edit.txt": "new\n", "add.txt": "added\n"},
    )
    changed = runner.changed_files(
        {"keep.txt": "same\n", "edit.txt": "old\n", "remove.txt": "gone\n"},
        {"keep.txt": "same\n", "edit.txt": "new\n", "add.txt": "added\n"},
    )

    assert "a/edit.txt" in diff
    assert "b/add.txt" in diff
    assert "a/remove.txt" in diff
    assert changed == ["add.txt", "edit.txt", "remove.txt"]


def test_structured_verifiers(tmp_path):
    runner = _load_eval_runner()
    (tmp_path / "notes.md").write_text("TermPilot eval ready\n", encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")

    contains = runner.run_verifier(
        {"type": "file_contains", "path": "notes.md", "contains": "eval ready"},
        cwd=tmp_path,
        timeout=30,
    )
    absent = runner.run_verifier(
        {"type": "file_absent", "path": "missing.tmp"},
        cwd=tmp_path,
        timeout=30,
    )
    json_match = runner.run_verifier(
        {"type": "json_match", "path": "config.json", "equals": {"enabled": True}},
        cwd=tmp_path,
        timeout=30,
    )
    composite = runner.run_verifier(
        {"type": "composite", "checks": [
            {"type": "file_contains", "path": "notes.md", "contains": "TermPilot"},
            {"type": "file_absent", "path": "missing.tmp"},
        ]},
        cwd=tmp_path,
        timeout=30,
    )

    assert contains.passed is True
    assert absent.passed is True
    assert json_match.passed is True
    assert composite.passed is True
    assert len(composite.details["checks"]) == 2


def test_classify_failure_reasons():
    runner = _load_eval_runner()

    reasons = runner.classify_failure({
        "status": "fail",
        "agent_exit": 1,
        "verifier": {"type": "file_contains", "passed": False},
        "missing_expected_files": ["hello.py"],
        "missing_expected_tool_calls": ["agent"],
        "changed_files": [],
        "session": "",
    })

    assert "agent_exit_nonzero" in reasons
    assert "verifier_failed:file_contains" in reasons
    assert "missing_expected_file" in reasons
    assert "missing_expected_tool_call" in reasons
    assert "no_diff" in reasons
    assert "no_session" in reasons


def test_expected_tool_call_detection(tmp_path):
    runner = _load_eval_runner()
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(json.dumps({
        "type": "transcript",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "delegating"},
                {"type": "tool_use", "name": "agent", "id": "toolu_1", "input": {}},
            ],
        },
    }) + "\n", encoding="utf-8")

    assert runner.collect_tool_calls(session_file) == ["agent"]
    assert runner.missing_expected_tool_calls(session_file, ["agent"]) == []
    assert runner.missing_expected_tool_calls(session_file, ["agent", "bash"]) == ["bash"]
    assert runner.missing_expected_tool_calls(None, ["agent"]) == ["agent"]


def test_run_task_trial_workspace_runtime_applies_to_source(tmp_path, monkeypatch):
    runner = _load_eval_runner()
    template = tmp_path / "evals" / "templates" / "trial"
    template.mkdir(parents=True)
    (template / "app.py").write_text('MESSAGE = "old"\n', encoding="utf-8")
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)

    def fake_run(command, *, cwd, env, text, capture_output, timeout):
        Path(cwd, "app.py").write_text('MESSAGE = "trial applied"\n', encoding="utf-8")
        return runner.subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    task = runner.EvalTask(
        id="trial",
        prompt="Update app.py",
        workspace="templates/trial",
        verifier={"type": "file_contains", "path": "app.py", "contains": "trial applied"},
        runtime="trial_workspace",
        expected_files=["app.py"],
    )

    result = runner.run_task(
        task,
        tmp_path / "runs",
        model="",
        permission_mode="bypassPermissions",
        json_summary=False,
        keep_workspaces="never",
    )

    assert result["status"] == "pass"
    assert result["runtime"] == "trial_workspace"
    assert result["changed_files"] == ["app.py"]


def test_build_run_summary_and_markdown_report(tmp_path):
    runner = _load_eval_runner()
    results = [
        {
            "id": "pass-task",
            "status": "pass",
            "duration_s": 1.2,
            "model": "glm-5.1",
            "tags": ["smoke"],
        },
        {
            "id": "fail-task",
            "status": "fail",
            "duration_s": 2.5,
            "model": "glm-5.1",
            "tags": ["smoke", "regression"],
            "agent_exit": 0,
            "verifier_exit": 1,
            "failure_reasons": ["verifier_failed:command"],
            "missing_expected_files": ["hello.py"],
            "missing_expected_tool_calls": ["agent"],
            "log": "/tmp/fail.log",
            "diff": "/tmp/fail.diff",
            "workspace_kept": True,
        },
    ]

    summary = runner.build_run_summary(
        results,
        run_dir=tmp_path,
        tasks_path=tmp_path / "tasks.jsonl",
        results_path=tmp_path / "results.jsonl",
        trajectories_path=tmp_path / "trajectories.jsonl",
    )
    report = runner.format_markdown_report(summary)

    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["by_tag"]["smoke"]["total"] == 2
    assert summary["by_tag"]["regression"]["failed"] == 1
    assert summary["failures"][0]["id"] == "fail-task"
    assert summary["failures"][0]["failure_reasons"] == ["verifier_failed:command"]
    assert summary["failures"][0]["missing_expected_tool_calls"] == ["agent"]
    assert "# TermPilot Eval Report" in report
    assert "`fail-task`" in report
    assert "verifier_failed:command" in report
    assert "Missing expected tool calls: agent" in report


def test_update_run_index_writes_index_and_latest(tmp_path):
    runner = _load_eval_runner()
    summary = {
        "run_dir": str(tmp_path / "runs" / "20260101T000000Z"),
        "tasks": str(tmp_path / "tasks.jsonl"),
        "total": 2,
        "passed": 1,
        "failed": 1,
        "timeout": 0,
        "pass_rate": 0.5,
        "duration_s": 3.7,
        "artifacts": {
            "report": str(tmp_path / "runs" / "20260101T000000Z" / "report.md"),
            "summary": str(tmp_path / "runs" / "20260101T000000Z" / "summary.json"),
        },
    }

    runner.update_run_index(tmp_path / "runs", summary)

    index_row = json.loads((tmp_path / "runs" / "index.jsonl").read_text(encoding="utf-8"))
    assert index_row["pass_rate"] == 0.5
    assert (tmp_path / "runs" / "latest.txt").read_text(encoding="utf-8").strip() == summary["run_dir"]


def test_append_trajectory_writes_jsonl(tmp_path):
    runner = _load_eval_runner()
    session_file = tmp_path / "task.session.jsonl"
    session_file.write_text(json.dumps({
        "type": "transcript",
        "sessionId": "session-1",
        "message": {"role": "user", "content": "Create file"},
    }), encoding="utf-8")
    task = runner.EvalTask(
        id="create-file",
        prompt="Create file",
        workspace="templates/create-file",
        verifier="true",
        tags=["smoke"],
    )
    result = {
        "id": "create-file",
        "status": "pass",
        "duration_s": 1.2,
        "workspace": "/tmp/work",
        "workspace_kept": False,
        "changed_files": ["hello.py"],
    }
    completed = runner.VerifierResult("command", True, exit_code=0, stdout="ok", stderr="")

    runner.append_trajectory(
        tmp_path / "trajectories.jsonl",
        task=task,
        result=result,
        session_path=session_file,
        model="glm-5.1",
        verifier_result=completed,
    )

    raw = (tmp_path / "trajectories.jsonl").read_text(encoding="utf-8")
    trajectory = json.loads(raw)
    assert trajectory["task_id"] == "create-file"
    assert trajectory["metadata"]["changed_files"] == ["hello.py"]
    assert trajectory["metadata"]["session_id"] == "session-1"
    assert trajectory["verifier"]["stdout"] == "ok"
