# TermPilot Eval Harness

This directory contains a small TerminalBench-like harness for TermPilot. It is
separate from the interactive runtime: the harness creates isolated workspaces,
runs `termpilot -p`, executes deterministic verifiers, and writes machine-readable
results.

## Layout

```text
evals/
├── run_eval.py          # runner
├── tasks/smoke.jsonl    # task dataset
├── templates/           # workspace fixtures
└── runs/                # generated artifacts, ignored by git
```

## Run

List tasks without calling the model:

```bash
uv run python evals/run_eval.py --dry-run
```

Run one task:

```bash
uv run python evals/run_eval.py --id fix-python-test
```

Run smoke tasks with a model override:

```bash
uv run python evals/run_eval.py --tag smoke --model glm-5.1
```

Use explicit eval runtime controls:

```bash
uv run python evals/run_eval.py \
  --tag smoke \
  --permission-mode bypassPermissions \
  --json-summary
```

## Task Shape

Each JSONL row includes:

- `id`: stable task id.
- `prompt`: prompt passed to TermPilot.
- `workspace`: fixture directory copied into a temporary workspace.
- `verifier`: final judge, either a shell command string or a structured verifier object.
- `timeout`: agent timeout in seconds.
- `tags`: task labels.
- `expected_files`: files that must exist after the run.
- `permission_mode`: optional per-task permission mode override.
- `settings`: optional per-task settings merged into the temporary config.
- `runtime`: optional runtime; currently `standard` or `trial_workspace`.
- `expected_tool_calls`: tool names that must appear in the captured session.

## Verifier Types

Legacy command verifiers still work:

```json
{"verifier": "python -m pytest -q"}
```

Structured verifiers reduce boilerplate for small tasks:

- `command`: run a shell command and use its exit code.
- `file_contains`: check that a file contains expected text.
- `file_absent`: check that a file does not exist.
- `json_match`: compare a JSON file to an expected value.
- `composite`: run multiple verifier checks and require all to pass.

Example:

```json
{
  "verifier": {
    "type": "composite",
    "checks": [
      {"type": "file_contains", "path": "README.md", "contains": "# Demo Project"},
      {"type": "file_absent", "path": "TODO.tmp"}
    ]
  }
}
```

## Results

Each run writes:

- `evals/runs/<timestamp>/results.jsonl`
- `evals/runs/<timestamp>/summary.json`
- `evals/runs/<timestamp>/report.md`
- `evals/runs/<timestamp>/trajectories.jsonl`
- one `<task-id>.log` with TermPilot and verifier output
- one `<task-id>.diff` with final workspace changes
- one `<task-id>.session.jsonl` copied from TermPilot's temporary session store

The runner copies the user's current TermPilot settings into a temporary config
directory, applies the requested `--permission-mode`, passes the same mode to
`termpilot -p`, and disables the interactive `sandbox` / `trialWorkspace`
runtime layers for repeatable standard eval runs. A task can still opt into the
external `trial_workspace` runtime, where the runner starts TermPilot in an
isolated trial workspace, applies successful changes back to the source fixture,
and verifies the applied source state. Before deleting the temporary config, it
converts the session JSONL into a portable trajectory row with task metadata and
verifier outcome.

`summary.json` is the machine-readable run aggregate: pass rate, counts by tag
and model, failure pointers, slowest tasks, and artifact paths. `report.md` is
the human-readable companion for quickly reviewing a run without opening every
task log.

Failure rows include normalized reasons such as `timeout`,
`agent_exit_nonzero`, `verifier_failed:<type>`, `missing_expected_file`,
`missing_expected_tool_call`, `no_diff`, and `no_session`. The runner also
appends a compact row to `evals/runs/index.jsonl` and writes
`evals/runs/latest.txt` so repeated runs are easy to compare.

The smoke task set covers basic file creation, bug fixes, multi-file edits,
command use, structured verifiers, permission-denial recovery, trial workspace
apply, and sub-agent delegation checks.
