# TermPilot Eval Harness

这个目录包含 TermPilot 的小型 TerminalBench-like harness。它独立于交互式
runtime：harness 会创建隔离 workspace，运行 `termpilot -p`，执行确定性的
verifier，并写出机器可读结果。

## 目录结构

```text
evals/
├── run_eval.py          # runner
├── tasks/smoke.jsonl    # 任务数据集
├── templates/           # workspace fixtures
└── runs/                # 生成产物，git 忽略
```

## 运行

只列出任务，不调用模型：

```bash
uv run python evals/run_eval.py --dry-run
```

运行单个任务：

```bash
uv run python evals/run_eval.py --id fix-python-test
```

用指定模型运行 smoke 任务：

```bash
uv run python evals/run_eval.py --tag smoke --model glm-5.1
```

使用显式 eval runtime 控制：

```bash
uv run python evals/run_eval.py \
  --tag smoke \
  --permission-mode bypassPermissions \
  --json-summary
```

## Task Shape

每一行 JSONL 包含：

- `id`：稳定任务 ID。
- `prompt`：传给 TermPilot 的 prompt。
- `workspace`：会被复制到临时目录的 fixture。
- `verifier`：最终判分规则，可以是 shell 命令字符串，也可以是结构化 verifier 对象。
- `timeout`：agent 超时时间，单位秒。
- `tags`：任务标签。
- `expected_files`：运行后必须存在的文件。
- `permission_mode`：可选的单任务权限模式覆盖。
- `settings`：可选的单任务 settings，会合并进临时配置。
- `runtime`：可选 runtime，目前支持 `standard` 和 `trial_workspace`。
- `expected_tool_calls`：必须出现在捕获 session 里的工具名。

## Verifier 类型

旧的命令型 verifier 仍然可用：

```json
{"verifier": "python -m pytest -q"}
```

结构化 verifier 可以减少小任务的样板代码：

- `command`：运行 shell 命令，用 exit code 判定。
- `file_contains`：检查文件是否包含指定文本。
- `file_absent`：检查文件不存在。
- `json_match`：比较 JSON 文件是否等于期望值。
- `composite`：组合多个 verifier，全部通过才算通过。

示例：

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

每次运行会写出：

- `evals/runs/<timestamp>/results.jsonl`
- `evals/runs/<timestamp>/summary.json`
- `evals/runs/<timestamp>/report.md`
- `evals/runs/<timestamp>/trajectories.jsonl`
- 每个任务一个 `<task-id>.log`，包含 TermPilot 和 verifier 输出
- 每个任务一个 `<task-id>.diff`，包含最终 workspace 变更
- 每个任务一个 `<task-id>.session.jsonl`，从 TermPilot 临时 session store 复制而来

Runner 会把用户当前 TermPilot settings 复制到临时配置目录，应用指定的
`--permission-mode`，把同一个权限模式传给 `termpilot -p`，并关闭交互式
`sandbox` / `trialWorkspace` runtime 层，保证标准 eval 可重复运行。任务也可以显式
选择外部 `trial_workspace` runtime：runner 会在隔离 trial workspace 中启动
TermPilot，成功后把变更 apply 回源 fixture，再验证源 workspace 的最终状态。
删除临时配置目录前，runner 会把 session JSONL 转换成可移植 trajectory row，
并附加任务 metadata 与 verifier 结果。

`summary.json` 是机器可读的运行聚合：通过率、按 tag/model 统计、失败产物路径、
最慢任务和所有 artifact 路径。`report.md` 是对应的人类可读报告，用来快速扫一遍
运行结果，而不需要逐个打开任务日志。

失败行会包含标准化原因，例如 `timeout`、`agent_exit_nonzero`、
`verifier_failed:<type>`、`missing_expected_file`、`missing_expected_tool_call`、
`no_diff` 和 `no_session`。Runner 还会追加一行到 `evals/runs/index.jsonl`，
并写入 `evals/runs/latest.txt`，方便比较多次运行结果。

当前 smoke task set 覆盖基础文件创建、bug 修复、多文件编辑、命令使用、
结构化 verifier、权限拒绝后的恢复、trial workspace apply，以及子 agent
delegation 检查。
