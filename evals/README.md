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

## Manual Validation Cases

The eval runner is non-interactive by design, but the same task behaviors can be
validated manually in TermPilot's interactive mode. These cases are useful when
debugging UX, permissions, tool cards, trial workspace flow, or sub-agent
delegation before turning the scenario into an automated eval.

Use a disposable workspace for manual tests:

```bash
mkdir -p /tmp/termpilot-eval-manual
```

### Case 1: Basic File Creation

```bash
mkdir -p /tmp/termpilot-eval-manual/create-cli
cd /tmp/termpilot-eval-manual/create-cli
uv run termpilot
```

Prompt:

```text
Create hello.py and test_hello.py. hello.py should read a name from argv and print 'Hello, <name>!'. Add a pytest test and run it.
```

Expected:

- `hello.py` and `test_hello.py` exist.
- `python -m pytest -q` passes.

### Case 2: Fix A Failing Test

```bash
cp -R evals/templates/fix-python-test /tmp/termpilot-eval-manual/fix-python-test
cd /tmp/termpilot-eval-manual/fix-python-test
uv run termpilot
```

Prompt:

```text
Fix the failing pytest test in this project. Run pytest before finishing.
```

Expected:

- TermPilot edits `calc.py`.
- `python -m pytest -q` passes.

### Case 3: File Contains Verifier Behavior

```bash
cp -R evals/templates/write-markdown-note /tmp/termpilot-eval-manual/write-markdown-note
cd /tmp/termpilot-eval-manual/write-markdown-note
uv run termpilot
```

Prompt:

```text
Create notes.md with a short note that contains the exact phrase 'TermPilot eval ready'.
```

Expected:

- `notes.md` exists.
- `grep "TermPilot eval ready" notes.md` finds the phrase.

### Case 4: File Deletion With Preservation

```bash
cp -R evals/templates/remove-temp-file /tmp/termpilot-eval-manual/remove-temp-file
cd /tmp/termpilot-eval-manual/remove-temp-file
uv run termpilot
```

Prompt:

```text
Remove temp.log from this workspace. Do not remove keep.txt.
```

Expected:

- `temp.log` is removed.
- `keep.txt` still exists and contains `keep me`.

### Case 5: Permission Denial Recovery

```bash
cp -R evals/templates/permission-denial-recovery /tmp/termpilot-eval-manual/permission-denial-recovery
cd /tmp/termpilot-eval-manual/permission-denial-recovery
uv run termpilot
```

Configure a deny rule for `secret.txt`, or manually deny access when prompted.

Prompt:

```text
First try to inspect secret.txt. That access is intentionally denied. Recover by reading fallback.txt and create result.txt containing only the phrase fallback-ok.
```

Expected:

- TermPilot recovers after denied access to `secret.txt`.
- `result.txt` exists and contains `fallback-ok`.

### Case 6: Trial Workspace Apply

```bash
cp -R evals/templates/trial-workspace-apply /tmp/termpilot-eval-manual/trial-workspace-apply
cd /tmp/termpilot-eval-manual/trial-workspace-apply
uv run termpilot
```

Commands and prompt:

```text
/trial start --copy
Update app.py so MESSAGE is exactly 'trial applied'.
/trial diff
/trial apply
```

Expected:

- `/trial diff` shows the `app.py` change.
- The source workspace is unchanged before `/trial apply`.
- After `/trial apply`, source `app.py` contains `trial applied`.

### Case 7: Sub-Agent Delegation

```bash
cp -R evals/templates/subagent-delegation /tmp/termpilot-eval-manual/subagent-delegation
cd /tmp/termpilot-eval-manual/subagent-delegation
uv run termpilot
```

Prompt:

```text
Use the agent tool with subagent_type=Explore to inspect alpha.txt and beta.txt, then create delegation-summary.md with both code words: alpha-ready and beta-ready.
```

Expected:

- The UI shows an `Explore` or `Delegation` agent card.
- `delegation-summary.md` exists.
- The file contains both `alpha-ready` and `beta-ready`.

### Case 8: Eval Runner Smoke Check

This case validates the non-interactive harness itself:

```bash
uv run python evals/run_eval.py --dry-run
uv run python evals/run_eval.py --id write-markdown-note --keep-workspaces fail
uv run python evals/run_eval.py --id remove-temp-file --keep-workspaces fail
uv run python evals/run_eval.py --id write-json-config --keep-workspaces fail
cat evals/runs/latest.txt
```

Expected:

- `--dry-run` lists all smoke tasks.
- The selected tasks pass.
- The latest run directory contains `summary.json`, `report.md`,
  `results.jsonl`, and `trajectories.jsonl`.
