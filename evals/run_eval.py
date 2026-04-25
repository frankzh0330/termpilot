"""TermPilot Evals Harness — TerminalBench-style evaluation runner.

Usage:
    python evals/run_eval.py                        # 跑全部
    python evals/run_eval.py --filter fix-python     # 只跑匹配的
    python evals/run_eval.py --model glm-5.1         # 覆盖模型
    python evals/run_eval.py --parallel 2            # 并行 2 个 task
    python evals/run_eval.py --dry-run               # 只打印不执行
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
SRC_DIR = REPO_ROOT / "src"
TASKS_FILE = EVALS_DIR / "tasks.jsonl"
LOGS_DIR = EVALS_DIR / "logs"
RUNS_DIR = EVALS_DIR / "runs"
RESULTS_FILE = EVALS_DIR / "eval_results.jsonl"
USER_SETTINGS = Path.home() / ".termpilot" / "settings.json"


def load_tasks(filter_pattern: str = "") -> list[dict[str, Any]]:
    """Load tasks from tasks.jsonl, optionally filtering by id."""
    tasks = []
    for line in TASKS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        task = json.loads(line)
        if filter_pattern and filter_pattern.lower() not in task["id"].lower():
            continue
        tasks.append(task)
    return tasks


def load_user_api_config() -> dict[str, str]:
    """Load API key and provider config from user's ~/.termpilot/settings.json."""
    if not USER_SETTINGS.exists():
        print(f"Error: {USER_SETTINGS} not found. Run 'termpilot setup' first.")
        sys.exit(1)
    data = json.loads(USER_SETTINGS.read_text(encoding="utf-8"))
    env = data.get("env", {})
    provider = data.get("provider", "")
    return {"provider": provider, "env": env}


def build_test_settings(api_config: dict[str, str]) -> dict[str, Any]:
    """Build a settings dict for the test run with bypass permissions."""
    settings: dict[str, Any] = {
        "provider": api_config["provider"],
        "env": dict(api_config["env"]),
        "permissions": {"defaultMode": "bypassPermissions"},
    }
    return settings


def detect_model(api_config: dict[str, Any], override: str | None = None) -> str:
    """Best-effort model label for result rows."""
    if override:
        return override
    env = api_config.get("env", {})
    if not isinstance(env, dict):
        return "unknown"
    provider = str(api_config.get("provider", "")).upper()
    candidates = [
        f"{provider}_MODEL",
        "TERMPILOT_MODEL",
        "OPENAI_MODEL",
        "ANTHROPIC_MODEL",
        "ZHIPU_MODEL",
        "DASHSCOPE_MODEL",
        "DEEPSEEK_MODEL",
        "MOONSHOT_MODEL",
        "OPENROUTER_MODEL",
    ]
    for key in candidates:
        value = env.get(key)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def count_tool_calls(session_jsonl: Path) -> int:
    """Count tool_use entries in a session JSONL file."""
    if not session_jsonl.exists():
        return 0
    count = 0
    for line in session_jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            msg = entry.get("message", {})
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        count += 1
        except json.JSONDecodeError:
            continue
    return count


def find_session_file(config_dir: Path, task_id: str) -> Path | None:
    """Find the most recent session JSONL file in the temp config dir."""
    projects_dir = config_dir / "projects"
    if not projects_dir.exists():
        return None
    # Find all .jsonl files recursively, return most recent
    jsonl_files = sorted(projects_dir.rglob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    return jsonl_files[0] if jsonl_files else None


def extract_token_count(log_text: str) -> int:
    """Extract token count from termpilot output."""
    # Look for patterns like "tokens: 1520" or "Token usage: ..."
    match = re.search(r"total[_ ]tokens[:\s]+(\d+)", log_text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"Cost:.*?(\d+)\s*tokens?", log_text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 0


def snapshot_workspace(work_dir: Path) -> dict[str, str]:
    """Capture a small text snapshot of the workspace for diffing."""
    snapshot: dict[str, str] = {}
    ignored_dirs = {".git", ".pytest_cache", "__pycache__", ".termpilot"}
    for path in sorted(work_dir.rglob("*")):
        rel = path.relative_to(work_dir).as_posix()
        if any(part in ignored_dirs for part in path.relative_to(work_dir).parts):
            continue
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 200_000:
                continue
            snapshot[rel] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    return snapshot


def build_workspace_diff(before: dict[str, str], after: dict[str, str]) -> str:
    """Build a unified diff for files changed by TermPilot."""
    import difflib

    chunks: list[str] = []
    all_files = sorted(set(before) | set(after))
    for rel in all_files:
        old = before.get(rel)
        new = after.get(rel)
        if old == new:
            continue
        old_lines = [] if old is None else old.splitlines(keepends=True)
        new_lines = [] if new is None else new.splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        ))
    return "".join(chunks)


def run_single_task(
        task: dict[str, Any],
        api_config: dict[str, str],
        model: str | None = None,
        run_dir: str | None = None,
        keep_workspaces: str = "fail",
) -> dict[str, Any]:
    """Run a single eval task and return result dict."""
    task_id = task["id"]
    prompt = task["prompt"]
    workspace = task.get("workspace", "")
    verifier = task["verifier"]
    timeout = task.get("timeout", 120)

    # Create temp workspace
    work_dir = tempfile.mkdtemp(prefix=f"termpilot-eval-{task_id}-")
    config_dir = tempfile.mkdtemp(prefix=f"termpilot-eval-config-{task_id}-")
    work_path = Path(work_dir)
    config_path = Path(config_dir)

    # Copy workspace template
    template_dir = EVALS_DIR / workspace
    if workspace and not template_dir.exists():
        raise FileNotFoundError(f"workspace template not found: {template_dir}")
    if workspace and template_dir.exists():
        for item in template_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, work_path / item.name)
            elif item.is_dir():
                shutil.copytree(item, work_path / item.name)
    before_snapshot = snapshot_workspace(work_path)

    # Write test settings.json
    settings = build_test_settings(api_config)
    settings_path = config_path / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    # Ensure logs dir exists
    output_dir = Path(run_dir) if run_dir else LOGS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / f"{task_id}.log"
    diff_path = output_dir / f"{task_id}.diff"
    workspace_archive = output_dir / f"{task_id}-workspace"

    result: dict[str, Any] = {
        "id": task_id,
        "status": "error",
        "duration_s": 0,
        "tool_calls": 0,
        "tokens": 0,
        "model": detect_model(api_config, model),
        "verifier_exit": -1,
        "log": str(log_path),
        "diff": str(diff_path),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # Run termpilot -p
        env = os.environ.copy()
        env["TERMPILOT_CONFIG_DIR"] = config_dir
        env["PYTHONPATH"] = (
            str(SRC_DIR)
            if not env.get("PYTHONPATH")
            else str(SRC_DIR) + os.pathsep + env["PYTHONPATH"]
        )

        # Fallback: try python -m termpilot
        cmd = [sys.executable, "-m", "termpilot", "-p", prompt]
        if model:
            cmd.extend(["--model", model])

        start_time = time.time()
        proc = subprocess.run(
            cmd,
            cwd=work_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.time() - start_time
        result["duration_s"] = round(duration, 1)

        # Save log
        log_content = (
            f"=== COMMAND ===\n{' '.join(cmd)}\n"
            f"=== WORKSPACE ===\n{work_dir}\n"
            f"=== STDOUT ===\n{proc.stdout}\n=== STDERR ===\n{proc.stderr}"
        )
        log_path.write_text(log_content, encoding="utf-8")

        # Extract stats
        result["tokens"] = extract_token_count(proc.stdout + proc.stderr)

        # Find session file for tool call count
        session_file = find_session_file(config_path, task_id)
        if session_file:
            result["tool_calls"] = count_tool_calls(session_file)

        # Run verifier
        try:
            verify_proc = subprocess.run(
                verifier,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=30,
                shell=True,
            )
            result["verifier_exit"] = verify_proc.returncode
            result["verifier_output"] = verify_proc.stdout.strip()[:500]
            result["status"] = "pass" if verify_proc.returncode == 0 else "fail"
        except subprocess.TimeoutExpired:
            result["verifier_exit"] = -1
            result["status"] = "fail"
            result["verifier_output"] = "verifier timed out"
        except Exception as e:
            result["verifier_exit"] = -1
            result["status"] = "fail"
            result["verifier_output"] = str(e)[:200]

        after_snapshot = snapshot_workspace(work_path)
        diff_text = build_workspace_diff(before_snapshot, after_snapshot)
        diff_path.write_text(diff_text or "(no workspace diff)\n", encoding="utf-8")
        result["changed_files"] = sorted(
            rel for rel in set(before_snapshot) | set(after_snapshot)
            if before_snapshot.get(rel) != after_snapshot.get(rel)
        )

    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["duration_s"] = timeout
        log_path.write_text(f"Task timed out after {timeout}s", encoding="utf-8")
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:500]
    finally:
        should_keep = (
            keep_workspaces == "all"
            or (keep_workspaces == "fail" and result.get("status") != "pass")
        )
        if should_keep and run_dir:
            if workspace_archive.exists():
                shutil.rmtree(workspace_archive, ignore_errors=True)
            shutil.copytree(work_path, workspace_archive)
            result["workspace"] = str(workspace_archive)
        # Cleanup temp dirs
        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(config_dir, ignore_errors=True)

    return result


def print_summary(results: list[dict[str, Any]]) -> None:
    """Print a summary table of results."""
    print(f"\n{'='*70}")
    print(f"  EVAL RESULTS — {len(results)} tasks")
    print(f"{'='*70}")

    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    errors = sum(1 for r in results if r["status"] in ("timeout", "error"))

    for r in results:
        status_icon = {"pass": "+", "fail": "x", "timeout": "!", "error": "?"}.get(r["status"], "?")
        print(f"  [{status_icon}] {r['id']:<25} {r['status']:<8} {r['duration_s']:>6.1f}s  "
              f"tools={r['tool_calls']}  tokens={r['tokens']}")

    print(f"{'-'*70}")
    print(f"  Total: {len(results)}  |  Pass: {passed}  |  Fail: {failed}  |  Error: {errors}")
    if results:
        total_time = sum(r["duration_s"] for r in results)
        total_tokens = sum(r["tokens"] for r in results)
        print(f"  Time: {total_time:.1f}s  |  Tokens: {total_tokens}")
    print(f"{'='*70}")
    print(f"  Results: {RESULTS_FILE}")
    print(f"  Logs:    {LOGS_DIR}/")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="TermPilot Evals Harness")
    parser.add_argument("--filter", default="", help="Filter tasks by id substring")
    parser.add_argument("--model", default=None, help="Override model")
    parser.add_argument("--parallel", type=int, default=1, help="Run N tasks in parallel")
    parser.add_argument("--dry-run", action="store_true", help="Print tasks without running")
    parser.add_argument(
        "--keep-workspaces",
        choices=["never", "fail", "all"],
        default="fail",
        help="Copy final workspaces into evals/runs for inspection",
    )
    args = parser.parse_args()

    tasks = load_tasks(args.filter)
    if not tasks:
        print("No tasks found.")
        return

    api_config = load_user_api_config()
    print(f"Provider: {api_config['provider']}")
    print(f"Model: {args.model or 'default'}")
    print(f"Tasks: {len(tasks)}")
    print()

    if args.dry_run:
        for t in tasks:
            print(f"  - {t['id']}: {t['prompt'][:60]}...")
        return

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / run_id
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    if args.parallel > 1:
        with ProcessPoolExecutor(max_workers=args.parallel) as pool:
            futures = {
                pool.submit(run_single_task, t, api_config, args.model, str(run_dir), args.keep_workspaces): t
                for t in tasks
            }
            for future in as_completed(futures):
                task = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = {
                        "id": task["id"],
                        "status": "error",
                        "error": str(e),
                        "duration_s": 0,
                        "tool_calls": 0,
                        "tokens": 0,
                        "model": args.model or "unknown",
                        "verifier_exit": -1,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                results.append(result)
                status_icon = {"pass": "+", "fail": "x"}.get(result["status"], "?")
                print(f"  [{status_icon}] {result['id']}: {result['status']} ({result['duration_s']}s)")
    else:
        for i, task in enumerate(tasks, 1):
            print(f"  [{i}/{len(tasks)}] Running: {task['id']}...")
            result = run_single_task(task, api_config, args.model, str(run_dir), args.keep_workspaces)
            results.append(result)
            status_icon = {"pass": "+", "fail": "x", "timeout": "!", "error": "?"}.get(result["status"], "?")
            print(f"  [{status_icon}] {result['id']}: {result['status']} ({result['duration_s']}s)")

    # Sort results by id for consistent output
    results.sort(key=lambda r: r["id"])

    # Write results
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print_summary(results)

    # Exit code: 0 if all pass, 1 otherwise
    sys.exit(0 if all(r["status"] == "pass" for r in results) else 1)


if __name__ == "__main__":
    main()
