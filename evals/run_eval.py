#!/usr/bin/env python3
"""Small TerminalBench-like harness for TermPilot.

The runner keeps eval state outside the product runtime:
1. copy a task fixture to an isolated workspace,
2. run `python -m termpilot -p <prompt>` in that workspace,
3. run a deterministic verifier command,
4. write JSONL results plus logs and diffs.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from termpilot.trajectory import build_trajectory_from_session

DEFAULT_TASKS = REPO_ROOT / "evals" / "tasks" / "smoke.jsonl"
DEFAULT_RUNS = REPO_ROOT / "evals" / "runs"
IGNORE_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


@dataclass(frozen=True)
class EvalTask:
    id: str
    prompt: str
    workspace: str
    verifier: str | dict[str, Any]
    timeout: int = 180
    tags: list[str] = field(default_factory=list)
    expected_files: list[str] = field(default_factory=list)
    expected_tool_calls: list[str] = field(default_factory=list)
    permission_mode: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    runtime: str = "standard"


@dataclass(frozen=True)
class VerifierResult:
    type: str
    passed: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TermPilot eval tasks.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS), help="JSONL task file")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS), help="Directory for run artifacts")
    parser.add_argument("--model", default="", help="Optional model override passed to TermPilot")
    parser.add_argument(
        "--permission-mode",
        choices=["default", "acceptEdits", "bypassPermissions", "dontAsk", "plan"],
        default="bypassPermissions",
        help="Permission mode passed to TermPilot during eval runs",
    )
    parser.add_argument(
        "--json-summary",
        action="store_true",
        help="Ask TermPilot to print a final one-shot JSON summary",
    )
    parser.add_argument("--id", action="append", default=[], help="Run only task id; repeatable")
    parser.add_argument("--tag", action="append", default=[], help="Run tasks matching tag; repeatable")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of tasks")
    parser.add_argument("--keep-workspaces", choices=["always", "fail", "never"], default="fail")
    parser.add_argument("--dry-run", action="store_true", help="List selected tasks without running")
    args = parser.parse_args()

    tasks = select_tasks(load_tasks(Path(args.tasks)), ids=set(args.id), tags=set(args.tag), limit=args.limit)
    if args.dry_run:
        for task in tasks:
            print(f"{task.id}\t{','.join(task.tags)}\t{task.workspace}")
        return 0

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.runs_dir).expanduser().resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"
    trajectories_path = run_dir / "trajectories.jsonl"

    failures = 0
    results: list[dict[str, Any]] = []
    for task in tasks:
        result = run_task(
            task,
            run_dir,
            model=args.model,
            permission_mode=args.permission_mode,
            json_summary=args.json_summary,
            keep_workspaces=args.keep_workspaces,
            trajectories_path=trajectories_path,
        )
        results.append(result)
        with open(results_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        status = result["status"]
        failures += 1 if status != "pass" else 0
        print(f"{status.upper():4} {task.id} ({result['duration_s']:.1f}s)")

    summary = build_run_summary(
        results,
        run_dir=run_dir,
        tasks_path=Path(args.tasks).expanduser().resolve(),
        results_path=results_path,
        trajectories_path=trajectories_path,
    )
    summary_path = run_dir / "summary.json"
    report_path = run_dir / "report.md"
    summary["artifacts"]["summary"] = str(summary_path)
    summary["artifacts"]["report"] = str(report_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(format_markdown_report(summary), encoding="utf-8")
    update_run_index(Path(args.runs_dir).expanduser().resolve(), summary)

    print(f"\nResults: {results_path}")
    print(f"Summary: {summary_path}")
    print(f"Report:  {report_path}")
    return 1 if failures else 0


def load_tasks(path: Path) -> list[EvalTask]:
    tasks: list[EvalTask] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            raw = json.loads(line)
            try:
                tasks.append(EvalTask(
                    id=str(raw["id"]),
                    prompt=str(raw["prompt"]),
                    workspace=str(raw["workspace"]),
                    verifier=_parse_verifier(raw["verifier"]),
                    timeout=int(raw.get("timeout") or 180),
                    tags=[str(item) for item in raw.get("tags", [])],
                    expected_files=[str(item) for item in raw.get("expected_files", [])],
                    expected_tool_calls=[str(item) for item in raw.get("expected_tool_calls", [])],
                    permission_mode=str(raw["permission_mode"]) if raw.get("permission_mode") else None,
                    settings=_parse_settings(raw.get("settings", {})),
                    runtime=str(raw.get("runtime") or "standard"),
                ))
            except KeyError as exc:
                raise ValueError(f"{path}:{line_no} missing required field {exc}") from exc
    return tasks


def select_tasks(
        tasks: list[EvalTask],
        *,
        ids: set[str],
        tags: set[str],
        limit: int,
) -> list[EvalTask]:
    selected = tasks
    if ids:
        selected = [task for task in selected if task.id in ids]
    if tags:
        selected = [task for task in selected if tags.intersection(task.tags)]
    if limit > 0:
        selected = selected[:limit]
    return selected


def run_task(
        task: EvalTask,
        run_dir: Path,
        *,
        model: str,
        permission_mode: str,
        json_summary: bool,
        keep_workspaces: str,
        trajectories_path: Path | None = None,
) -> dict[str, Any]:
    started = time.time()
    template = (REPO_ROOT / "evals" / task.workspace).resolve()
    if not template.exists():
        raise FileNotFoundError(f"Task workspace template not found: {template}")

    workspace = Path(tempfile.mkdtemp(prefix=f"termpilot-eval-{task.id}-"))
    config_dir = Path(tempfile.mkdtemp(prefix=f"termpilot-eval-config-{task.id}-"))
    task_log = run_dir / f"{task.id}.log"
    task_diff = run_dir / f"{task.id}.diff"
    keep_workspace = True
    trial_manager = None
    trial_workspace = None
    runtime_cwd = workspace
    effective_permission_mode = task.permission_mode or permission_mode

    try:
        copy_fixture(template, workspace)
        before = snapshot_workspace(workspace)
        if task.runtime == "trial_workspace":
            from termpilot.workspace import TrialWorkspaceConfig, TrialWorkspaceManager

            trial_manager = TrialWorkspaceManager(TrialWorkspaceConfig(
                backend="copy",
                root=str(run_dir / "_trial-workspaces"),
                prefer_git_worktree=False,
            ))
            trial_workspace = trial_manager.create(workspace, purpose=f"eval:{task.id}")
            runtime_cwd = Path(trial_workspace.workspace_path)
        elif task.runtime != "standard":
            raise ValueError(f"Unknown eval runtime: {task.runtime}")

        env = build_eval_env(
            config_dir,
            permission_mode=effective_permission_mode,
            settings_override=task.settings,
        )
        command = build_agent_command(
            task,
            model=model,
            permission_mode=effective_permission_mode,
            cwd=runtime_cwd,
            json_summary=json_summary,
        )
        if model:
            env["TERMPILOT_MODEL"] = model

        agent_proc = subprocess.run(
            command,
            cwd=runtime_cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=task.timeout,
        )
        if task.runtime == "trial_workspace" and agent_proc.returncode == 0 and trial_manager and trial_workspace:
            trial_manager.apply(trial_workspace.id)
        verifier_result = run_verifier(
            task.verifier,
            cwd=workspace,
            timeout=max(30, min(task.timeout, 180)),
        )
        after = snapshot_workspace(workspace)
        diff_text = build_diff(before, after)
        task_log.write_text(format_log(agent_proc, verifier_result, workspace), encoding="utf-8")
        task_diff.write_text(diff_text, encoding="utf-8")
        session_copy = copy_latest_session(config_dir, run_dir, task.id)

        missing_expected = [path for path in task.expected_files if path not in after]
        missing_tool_calls = missing_expected_tool_calls(session_copy, task.expected_tool_calls)
        passed = (
            agent_proc.returncode == 0
            and verifier_result.passed
            and not missing_expected
            and not missing_tool_calls
        )
        keep_workspace = should_keep_workspace(passed, keep_workspaces)
        result = {
            "id": task.id,
            "status": "pass" if passed else "fail",
            "duration_s": round(time.time() - started, 2),
            "model": model or "settings-default",
            "permission_mode": effective_permission_mode,
            "runtime": task.runtime,
            "agent_exit": agent_proc.returncode,
            "verifier": serialize_verifier_result(verifier_result),
            "verifier_exit": verifier_result.exit_code,
            "verifier_output": (verifier_result.stdout + verifier_result.stderr).strip()[:4000],
            "missing_expected_files": missing_expected,
            "missing_expected_tool_calls": missing_tool_calls,
            "changed_files": changed_files(before, after),
            "log": str(task_log),
            "diff": str(task_diff),
            "session": str(session_copy) if session_copy else "",
            "trajectory": str(trajectories_path) if trajectories_path else "",
            "workspace": str(workspace),
            "runtime_workspace": str(runtime_cwd),
            "trial_workspace": str(trial_workspace.workspace_path) if trial_workspace else "",
            "workspace_kept": keep_workspace,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tags": task.tags,
        }
        result["failure_reasons"] = classify_failure(result)
        if trajectories_path:
            append_trajectory(
                trajectories_path,
                task=task,
                result=result,
                session_path=session_copy,
                model=model,
                verifier_result=verifier_result,
            )
        return result
    except subprocess.TimeoutExpired as exc:
        keep_workspace = should_keep_workspace(False, keep_workspaces)
        task_log.write_text(f"TIMEOUT after {exc.timeout}s\n{exc}", encoding="utf-8")
        session_copy = copy_latest_session(config_dir, run_dir, task.id)
        result = {
            "id": task.id,
            "status": "timeout",
            "duration_s": round(time.time() - started, 2),
            "model": model or "settings-default",
            "permission_mode": effective_permission_mode,
            "runtime": task.runtime,
            "log": str(task_log),
            "diff": str(task_diff),
            "session": str(session_copy) if session_copy else "",
            "trajectory": str(trajectories_path) if trajectories_path else "",
            "workspace": str(workspace),
            "runtime_workspace": str(runtime_cwd),
            "trial_workspace": str(trial_workspace.workspace_path) if trial_workspace else "",
            "workspace_kept": keep_workspace,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tags": task.tags,
        }
        result["failure_reasons"] = classify_failure(result)
        if trajectories_path:
            append_trajectory(
                trajectories_path,
                task=task,
                result=result,
                session_path=session_copy,
                model=model,
                verifier_result=None,
            )
        return result
    finally:
        if trial_manager and trial_workspace and not keep_workspace:
            trial_manager.discard(trial_workspace.id)
        shutil.rmtree(config_dir, ignore_errors=True)
        if not keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)


def build_agent_command(
        task: EvalTask,
        *,
        model: str,
        permission_mode: str,
        cwd: Path,
        json_summary: bool,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "termpilot",
        "-p",
        task.prompt,
        "--permission-mode",
        permission_mode,
        "--cwd",
        str(cwd),
    ]
    if model:
        command.extend(["--model", model])
    if json_summary:
        command.append("--json-summary")
    return command


def build_eval_env(
        config_dir: Path,
        *,
        permission_mode: str = "bypassPermissions",
        settings_override: dict[str, Any] | None = None,
) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["TERMPILOT_CONFIG_DIR"] = str(config_dir)

    source_settings = Path.home() / ".termpilot" / "settings.json"
    target_settings = config_dir / "settings.json"
    config_dir.mkdir(parents=True, exist_ok=True)
    if source_settings.exists():
        try:
            settings = json.loads(source_settings.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            settings = {}
    else:
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    settings["sandbox"] = {**settings.get("sandbox", {}), "enabled": False}
    settings["trialWorkspace"] = {**settings.get("trialWorkspace", {}), "enabled": False}
    if settings_override:
        settings = _deep_merge(settings, settings_override)
    permissions = settings.setdefault("permissions", {})
    permissions["mode"] = permission_mode
    env["TERMPILOT_PERMISSION_MODE"] = permission_mode
    target_settings.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return env


def _parse_verifier(raw: Any) -> str | dict[str, Any]:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return dict(raw)
    raise ValueError("verifier must be a command string or an object")


def _parse_settings(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    raise ValueError("settings must be an object")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def run_verifier(verifier: str | dict[str, Any], *, cwd: Path, timeout: int) -> VerifierResult:
    if isinstance(verifier, str):
        return run_command_verifier(verifier, cwd=cwd, timeout=timeout)

    verifier_type = str(verifier.get("type", "command"))
    if verifier_type == "command":
        command = str(verifier.get("command", ""))
        return run_command_verifier(command, cwd=cwd, timeout=timeout)
    if verifier_type == "file_contains":
        return run_file_contains_verifier(verifier, cwd=cwd)
    if verifier_type == "file_absent":
        return run_file_absent_verifier(verifier, cwd=cwd)
    if verifier_type == "json_match":
        return run_json_match_verifier(verifier, cwd=cwd)
    if verifier_type == "composite":
        checks = verifier.get("checks", [])
        if not isinstance(checks, list):
            return VerifierResult("composite", False, stderr="checks must be a list")
        results = [run_verifier(check, cwd=cwd, timeout=timeout) for check in checks]
        passed = all(result.passed for result in results)
        return VerifierResult(
            "composite",
            passed,
            exit_code=0 if passed else 1,
            stdout="\n".join(result.stdout for result in results if result.stdout),
            stderr="\n".join(result.stderr for result in results if result.stderr),
            details={"checks": [serialize_verifier_result(result) for result in results]},
        )

    return VerifierResult(verifier_type, False, stderr=f"unknown verifier type: {verifier_type}")


def run_command_verifier(command: str, *, cwd: Path, timeout: int) -> VerifierResult:
    if not command:
        return VerifierResult("command", False, stderr="command is required")
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return VerifierResult(
            "command",
            False,
            exit_code=None,
            stdout=exc.stdout or "",
            stderr=f"verifier timed out after {exc.timeout}s",
            details={"command": command, "timeout_s": exc.timeout},
        )
    return VerifierResult(
        "command",
        proc.returncode == 0,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        details={"command": command},
    )


def run_file_contains_verifier(config: dict[str, Any], *, cwd: Path) -> VerifierResult:
    rel_path = str(config.get("path", ""))
    expected = str(config.get("contains", config.get("text", "")))
    path = cwd / rel_path
    if not rel_path:
        return VerifierResult("file_contains", False, stderr="path is required")
    if not path.exists():
        return VerifierResult("file_contains", False, stderr=f"missing file: {rel_path}")
    content = path.read_text(encoding="utf-8", errors="replace")
    passed = expected in content
    return VerifierResult(
        "file_contains",
        passed,
        exit_code=0 if passed else 1,
        stdout=f"{rel_path} contains expected text" if passed else "",
        stderr="" if passed else f"{rel_path} does not contain expected text",
        details={"path": rel_path, "contains": expected},
    )


def run_file_absent_verifier(config: dict[str, Any], *, cwd: Path) -> VerifierResult:
    rel_path = str(config.get("path", ""))
    if not rel_path:
        return VerifierResult("file_absent", False, stderr="path is required")
    path = cwd / rel_path
    passed = not path.exists()
    return VerifierResult(
        "file_absent",
        passed,
        exit_code=0 if passed else 1,
        stdout=f"{rel_path} is absent" if passed else "",
        stderr="" if passed else f"{rel_path} still exists",
        details={"path": rel_path},
    )


def run_json_match_verifier(config: dict[str, Any], *, cwd: Path) -> VerifierResult:
    rel_path = str(config.get("path", ""))
    expected = config.get("equals", config.get("expected"))
    if not rel_path:
        return VerifierResult("json_match", False, stderr="path is required")
    if expected is None:
        return VerifierResult("json_match", False, stderr="equals/expected is required")
    path = cwd / rel_path
    if not path.exists():
        return VerifierResult("json_match", False, stderr=f"missing file: {rel_path}")
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return VerifierResult("json_match", False, stderr=f"invalid JSON in {rel_path}: {exc}")
    passed = actual == expected
    return VerifierResult(
        "json_match",
        passed,
        exit_code=0 if passed else 1,
        stdout=f"{rel_path} matches expected JSON" if passed else "",
        stderr="" if passed else f"{rel_path} JSON did not match expected value",
        details={"path": rel_path, "expected": expected, "actual": actual},
    )


def serialize_verifier_result(result: VerifierResult) -> dict[str, Any]:
    return {
        "type": result.type,
        "passed": result.passed,
        "exit_code": result.exit_code,
        "stdout": result.stdout[:4000],
        "stderr": result.stderr[:4000],
        "details": result.details,
    }


def collect_tool_calls(session_path: Path | None) -> list[str]:
    if not session_path or not session_path.exists():
        return []
    calls: list[str] = []
    with open(session_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = event.get("message") if isinstance(event, dict) else None
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name"):
                    calls.append(str(block["name"]))
    return calls


def missing_expected_tool_calls(session_path: Path | None, expected: list[str]) -> list[str]:
    if not expected:
        return []
    observed = set(collect_tool_calls(session_path))
    return [name for name in expected if name not in observed]


def classify_failure(result: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    status = result.get("status")
    if status == "timeout":
        reasons.append("timeout")
    if result.get("agent_exit") not in (None, 0):
        reasons.append("agent_exit_nonzero")
    verifier = result.get("verifier")
    if isinstance(verifier, dict) and verifier.get("passed") is False:
        reasons.append(f"verifier_failed:{verifier.get('type', 'unknown')}")
    elif result.get("verifier_exit") not in (None, 0):
        reasons.append("verifier_failed")
    if result.get("missing_expected_files"):
        reasons.append("missing_expected_file")
    if result.get("missing_expected_tool_calls"):
        reasons.append("missing_expected_tool_call")
    if status != "pass" and not result.get("changed_files"):
        reasons.append("no_diff")
    if status != "pass" and not result.get("session"):
        reasons.append("no_session")
    return reasons or (["unknown"] if status != "pass" else [])


def build_run_summary(
        results: list[dict[str, Any]],
        *,
        run_dir: Path,
        tasks_path: Path,
        results_path: Path,
        trajectories_path: Path,
) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.get("status") == "pass")
    failed = sum(1 for result in results if result.get("status") == "fail")
    timed_out = sum(1 for result in results if result.get("status") == "timeout")
    duration_s = round(sum(float(result.get("duration_s") or 0) for result in results), 2)

    by_tag: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    for result in results:
        status = str(result.get("status", "unknown"))
        model = str(result.get("model") or "settings-default")
        model_bucket = by_model.setdefault(model, {"total": 0, "passed": 0, "failed": 0, "timeout": 0})
        _add_status(model_bucket, status)

        tags = result.get("tags") if isinstance(result.get("tags"), list) else []
        for tag in tags or ["untagged"]:
            tag_bucket = by_tag.setdefault(str(tag), {"total": 0, "passed": 0, "failed": 0, "timeout": 0})
            _add_status(tag_bucket, status)

    failures = [
        {
            "id": result.get("id", ""),
            "status": result.get("status", ""),
            "duration_s": result.get("duration_s", 0),
            "agent_exit": result.get("agent_exit"),
            "verifier_exit": result.get("verifier_exit"),
            "missing_expected_files": result.get("missing_expected_files", []),
            "missing_expected_tool_calls": result.get("missing_expected_tool_calls", []),
            "failure_reasons": result.get("failure_reasons", []),
            "log": result.get("log", ""),
            "diff": result.get("diff", ""),
            "workspace": result.get("workspace", ""),
            "runtime": result.get("runtime", "standard"),
            "runtime_workspace": result.get("runtime_workspace", ""),
            "trial_workspace": result.get("trial_workspace", ""),
            "workspace_kept": result.get("workspace_kept", False),
        }
        for result in results
        if result.get("status") != "pass"
    ]
    slowest = sorted(
        (
            {
                "id": result.get("id", ""),
                "status": result.get("status", ""),
                "duration_s": result.get("duration_s", 0),
            }
            for result in results
        ),
        key=lambda item: float(item["duration_s"] or 0),
        reverse=True,
    )[:5]

    return {
        "run_dir": str(run_dir),
        "tasks": str(tasks_path),
        "total": total,
        "passed": passed,
        "failed": failed,
        "timeout": timed_out,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "duration_s": duration_s,
        "by_model": by_model,
        "by_tag": by_tag,
        "failures": failures,
        "slowest": slowest,
        "artifacts": {
            "results": str(results_path),
            "trajectories": str(trajectories_path),
        },
    }


def _add_status(bucket: dict[str, Any], status: str) -> None:
    bucket["total"] = int(bucket.get("total", 0)) + 1
    if status == "pass":
        bucket["passed"] = int(bucket.get("passed", 0)) + 1
    elif status == "timeout":
        bucket["timeout"] = int(bucket.get("timeout", 0)) + 1
    else:
        bucket["failed"] = int(bucket.get("failed", 0)) + 1


def format_markdown_report(summary: dict[str, Any]) -> str:
    pass_rate = float(summary.get("pass_rate") or 0) * 100
    lines = [
        "# TermPilot Eval Report",
        "",
        f"- Tasks: {summary.get('total', 0)}",
        f"- Passed: {summary.get('passed', 0)}",
        f"- Failed: {summary.get('failed', 0)}",
        f"- Timeout: {summary.get('timeout', 0)}",
        f"- Pass rate: {pass_rate:.1f}%",
        f"- Total task time: {summary.get('duration_s', 0)}s",
        "",
        "## By Tag",
        "",
        "| Tag | Total | Passed | Failed | Timeout |",
        "|---|---:|---:|---:|---:|",
    ]
    by_tag = summary.get("by_tag", {})
    if by_tag:
        for tag, bucket in sorted(by_tag.items()):
            lines.append(_format_bucket_row(tag, bucket))
    else:
        lines.append("| - | 0 | 0 | 0 | 0 |")

    lines.extend([
        "",
        "## By Model",
        "",
        "| Model | Total | Passed | Failed | Timeout |",
        "|---|---:|---:|---:|---:|",
    ])
    for model, bucket in sorted(summary.get("by_model", {}).items()):
        lines.append(_format_bucket_row(model, bucket))

    lines.extend(["", "## Failures", ""])
    failures = summary.get("failures", [])
    if failures:
        for failure in failures:
            kept = "kept" if failure.get("workspace_kept") else "removed"
            lines.append(
                f"- `{failure.get('id')}`: {failure.get('status')} "
                f"(agent={failure.get('agent_exit')}, verifier={failure.get('verifier_exit')}, workspace={kept})"
            )
            if failure.get("missing_expected_files"):
                lines.append(f"  Missing expected files: {', '.join(failure['missing_expected_files'])}")
            if failure.get("missing_expected_tool_calls"):
                lines.append(f"  Missing expected tool calls: {', '.join(failure['missing_expected_tool_calls'])}")
            if failure.get("failure_reasons"):
                lines.append(f"  Reasons: {', '.join(failure['failure_reasons'])}")
            lines.append(f"  Log: `{failure.get('log')}`")
            lines.append(f"  Diff: `{failure.get('diff')}`")
    else:
        lines.append("No failures.")

    lines.extend(["", "## Slowest Tasks", ""])
    for item in summary.get("slowest", []):
        lines.append(f"- `{item.get('id')}`: {item.get('duration_s')}s ({item.get('status')})")

    artifacts = summary.get("artifacts", {})
    lines.extend([
        "",
        "## Artifacts",
        "",
        f"- Results: `{artifacts.get('results', '')}`",
        f"- Trajectories: `{artifacts.get('trajectories', '')}`",
        f"- Summary JSON: `{artifacts.get('summary', '')}`",
    ])
    return "\n".join(lines) + "\n"


def update_run_index(runs_dir: Path, summary: dict[str, Any]) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    index_row = {
        "run_dir": summary.get("run_dir"),
        "tasks": summary.get("tasks"),
        "total": summary.get("total"),
        "passed": summary.get("passed"),
        "failed": summary.get("failed"),
        "timeout": summary.get("timeout"),
        "pass_rate": summary.get("pass_rate"),
        "duration_s": summary.get("duration_s"),
        "report": summary.get("artifacts", {}).get("report", ""),
        "summary": summary.get("artifacts", {}).get("summary", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(runs_dir / "index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(index_row, ensure_ascii=False) + "\n")
    (runs_dir / "latest.txt").write_text(str(summary.get("run_dir", "")) + "\n", encoding="utf-8")


def _format_bucket_row(name: str, bucket: dict[str, Any]) -> str:
    return (
        f"| {name} | {bucket.get('total', 0)} | {bucket.get('passed', 0)} | "
        f"{bucket.get('failed', 0)} | {bucket.get('timeout', 0)} |"
    )


def copy_fixture(template: Path, workspace: Path) -> None:
    for item in template.iterdir():
        target = workspace / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def copy_latest_session(config_dir: Path, run_dir: Path, task_id: str) -> Path | None:
    sessions = sorted(
        config_dir.glob("projects/**/*.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not sessions:
        return None
    target = run_dir / f"{task_id}.session.jsonl"
    shutil.copy2(sessions[0], target)
    return target


def append_trajectory(
        path: Path,
        *,
        task: EvalTask,
        result: dict[str, Any],
        session_path: Path | None,
        model: str,
        verifier_result: VerifierResult | None,
) -> None:
    verifier = {
        "command": task.verifier if isinstance(task.verifier, str) else task.verifier.get("command", ""),
        "passed": result["status"] == "pass",
        "type": verifier_result.type if verifier_result else None,
        "exit_code": verifier_result.exit_code if verifier_result else None,
        "stdout": verifier_result.stdout[:4000] if verifier_result else "",
        "stderr": verifier_result.stderr[:4000] if verifier_result else "",
    }
    trajectory = build_trajectory_from_session(
        session_path,
        task_id=task.id,
        prompt=task.prompt,
        metadata={
            "model": model or "settings-default",
            "duration_s": result.get("duration_s"),
            "status": result.get("status"),
            "workspace": result.get("workspace"),
            "runtime": result.get("runtime", "standard"),
            "runtime_workspace": result.get("runtime_workspace"),
            "trial_workspace": result.get("trial_workspace"),
            "workspace_kept": result.get("workspace_kept"),
            "changed_files": result.get("changed_files", []),
            "expected_tool_calls": task.expected_tool_calls,
            "missing_expected_tool_calls": result.get("missing_expected_tool_calls", []),
            "tags": task.tags,
        },
        verifier=verifier,
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(trajectory, ensure_ascii=False) + "\n")


def snapshot_workspace(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in IGNORE_DIRS for part in Path(rel).parts):
            continue
        files[rel] = path.read_text(encoding="utf-8", errors="replace")
    return files


def build_diff(before: dict[str, str], after: dict[str, str]) -> str:
    parts: list[str] = []
    for rel in sorted(set(before) | set(after)):
        old = before.get(rel, "").splitlines(keepends=True)
        new = after.get(rel, "").splitlines(keepends=True)
        if old == new:
            continue
        parts.extend(difflib.unified_diff(old, new, fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    return "".join(parts)


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return [rel for rel in sorted(set(before) | set(after)) if before.get(rel) != after.get(rel)]


def format_log(agent_proc: subprocess.CompletedProcess[str], verifier_result: VerifierResult, workspace: Path) -> str:
    return (
        f"WORKSPACE: {workspace}\n\n"
        "=== TERMPILOT STDOUT ===\n"
        f"{agent_proc.stdout}\n"
        "=== TERMPILOT STDERR ===\n"
        f"{agent_proc.stderr}\n"
        "=== VERIFIER SUMMARY ===\n"
        f"{json.dumps(serialize_verifier_result(verifier_result), ensure_ascii=False, indent=2)}\n"
        "=== VERIFIER STDOUT ===\n"
        f"{verifier_result.stdout}\n"
        "=== VERIFIER STDERR ===\n"
        f"{verifier_result.stderr}\n"
    )


def should_keep_workspace(passed: bool, policy: str) -> bool:
    if policy == "always":
        return True
    if policy == "never":
        return False
    return not passed


if __name__ == "__main__":
    raise SystemExit(main())
