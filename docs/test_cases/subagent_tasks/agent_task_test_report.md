# 功能优化后测试用例

## CASE-1: Agent 工具触发
输入 "分析项目设计模式"，验证 Explore agent 被触发
### 改进前
大项目的阅读分析过程时间较久，看起来像一直卡在 Running Explore agent...
等很久突然冒出来结果，且输出不够概括，再输入 `/details` 命令展示的明细又比较突兀,如下图
输入后等了几分钟才出来下面的结果

![CASE-1](images/beforeimprove_explore.png)
![CASE-1](images/beforeimprove_explore_sub1.png)
![CASE-1](images/beforeimprove_explore_sub2.png)
![CASE-1](images/beforeimprove_explore_details.png)

### 改进后
如下图可以看到阶段子agent会回传状态，渐进输出进度，提高用户体验
![CASE-1](images/improved_explore.png)
**返回模块总结列表(部分图片):**
![CASE-1](images/improved_explore_sub1.png)
![CASE-1](images/improved_explore_sub2.png)
![CASE-1](images/improved_explore_details.png)
**/details 返回的部分图片**
![CASE-1](images/improved_explore_details2.png)


## CASE-2: Slash 命令 + drain 并发安全
输入: 帮我写一个 hello world,等模型开始响应时（看到 Coalescing…），立刻输入: `/clear`

预期: `/clear` 会等当前修改文件的会话完成后再执行，不会丢失或错乱tasks

**如下图当输入一个任务后未等执行结束就输入slash command, 不会打断task的执行，避免了task执行状态混乱，
上下文逻辑偏差，保证了task stack顺序弹出**
![CASE-2](images/slash_command_task_interrupt.png)
![CASE-2](images/slash_command_task_interrupt2.png)
**当task涉及多轮对话时，仍然会完成后再执行slash command**
![CASE-2](images/slash_command_task_interrupt3.png)


## CASE-3: Agent Runtime Records + Follow-up

输入: 请用 Explore agent 简要查看 `src/termpilot/tools/agent.py` 的职责

预期:
- Explore agent 被触发，并在 UI 中展示阶段状态。
- 完成后生成 `agent_id`，例如 `agent-8fbd6830`。
- runtime record 包含 `agent_type`、`status`、`transcript_path`、`summary`。
- `transcript_path` 指向 `~/.termpilot/projects/.../agent-runtime/agent-xxxxxxxx.jsonl`。

### Explore agent 执行过程

如下图，Explore agent 会显示 `read_file` 和 `summarizing` 等状态，完成后主屏只展示摘要卡片，长结果折叠到 `/details`。

![CASE-3](images/agent_runtime_explore_progress.png)
![CASE-3](images/agent_runtime_explore_summary.png)

### agent_task_list 查询运行记录

输入: 用 `agent_task_list` 查看当前 agent runtime records

预期: 能看到刚才完成的 Explore agent 记录，状态为 `completed`，并展示 agent id、类型、描述和 foreground/local 执行模式。

![CASE-3](images/agent_runtime_task_list.png)
![CASE-3](images/agent_runtime_task_list_detail.png)

### agent_task_get 查看详情

输入: 用 `agent_task_get` 查看 `agent-8fbd6830` 的详情

预期: 返回结构化 record，包含 id、agent_type、description、prompt、status、transcript_path、summary 等信息；主回答会把关键信息整理成人类可读表格。

![CASE-3](images/agent_runtime_task_get_card.png)
![CASE-3](images/agent_runtime_task_get_summary.png)

### agent_send 发送 follow-up

输入: 向 `agent-8fbd6830` 发送 follow-up：再补充说明它和 `task.py` 的关系

预期: TermPilot 会加载该 agent 的历史上下文和 transcript，追加 follow-up 后继续让同一个子代理回答，而不是重新创建一个无上下文的新 agent。

![CASE-3](images/agent_runtime_followup_progress.png)
![CASE-3](images/agent_runtime_followup_summary.png)

### 验证结论

这组测试确认了子代理 runtime record 的完整闭环：

- `agent` 工具会为每次子代理运行创建持久化记录。
- `agent_task_list` 可以列出当前项目的 agent runtime records。
- `agent_task_get` 可以查看单个 agent 的详情和 transcript 路径。
- `agent_send` 可以基于历史 transcript 做 follow-up。
- UI 仍保持安静型输出：主屏展示摘要，完整内容通过 `/details` 查看。


## CASE-4: 批量委派 3 个 Explore agent

原独立的 Batch Agent 用例（分别检查 `cli.py`、`api.py`、`context.py`）和本 CASE 都验证同一条 batch delegation 主链路。前者主要证明多文件分析能触发 `Running 3 delegated agents...`，后者进一步补充了 runtime record、`agent_task_list` 和三模块合并总结，因此这里合并为一个完整的批量委派测试。

### 早期多文件批量委派验证

输入: 分别检查 `cli.py`、`api.py`、`context.py` 的主要功能

预期: 触发 batch delegation，UI 显示 `Running 3 delegated agents...` / `Delegation completed`，并返回 3 个 agent 的部分结果。

![CASE-4](images/batch_delegation_summary.png)
![CASE-4](images/delegation_result_1.png)
![CASE-4](images/delegation_result_2.png)
![CASE-4](images/delegation_result_3.png)

输入: 请分别用 Explore agent 检查 `src/termpilot/tools/agent.py`、`src/termpilot/agent_tasks.py`、`src/termpilot/queue.py` 的职责，并合并总结

预期:
- UI 显示 `Running 3 delegated agents...`。
- 完成后显示 `Delegation completed` 卡片。
- 3 个子代理分别完成，并在汇总中显示 `3/3 succeeded`。
- 主回答合并总结三个模块的关系，而不是简单拼接三个子代理原文。

### 批量委派结果

如下图，TermPilot 将任务拆成 3 个 Explore 子代理，分别检查业务引擎层、数据持久层和通信枢纽层。最终合并总结为 `agent.py -> agent_tasks.py -> queue.py` 的三层协作关系。

![CASE-4](images/batch_delegation_architecture_summary.png)

### agent_task_list 验证批量记录

输入: 调用 `agent_task_list`

预期: 能看到新增的 3 条 Explore agent runtime records，状态均为 `completed`。

![CASE-4](images/batch_delegation_agent_task_list.png)

### 验证结论

这组测试确认了批量委派链路：

- `agent.tasks` 可以一次派发多个独立子任务。
- 每个子任务都会产生独立 `agent_id` 和 runtime record。
- 批量结果会在 UI 中以 `Delegation` 卡片汇总。
- 主循环可以基于多个子代理结果做二次综合总结。


## CASE-5: 后台 agent 启动、通知与 follow-up

输入: 请启动一个后台 Explore agent，检查 `docs/task-delegation.zh-CN.md` 里 AgentTask runtime 的说明，完成后通知我

预期:
- 前台工具卡片返回 `async_launched`。
- 返回内容包含后台 agent id，例如 `agent-eca8b269`。
- 后台 agent 完成后，通过消息队列通知主循环。
- `agent_send` 可以给该 agent 发送 follow-up；如果 agent 仍在运行，应返回类似 `already running`，如果已经完成，则继续基于 transcript 回答。

### 启动后台 Explore agent

如下图，工具卡片显示后台 agent 已启动，返回 `async_launched` 和 `agent_id`。主回答告知用户后台任务正在运行，完成后会通知。

![CASE-5](images/background_agent_launched.png)

### agent_send 发送 follow-up

输入: 请调用 `agent_send` 给刚才的 agent_id 发送：继续补充细节

如下图，当前测试中后台 agent 已完成，因此 `agent_send` 正常追加 follow-up，并提示子代理会在完成后合并返回完整结果。如果任务仍在运行，预期应返回 already running 类提示，需要换一个更慢的任务重试该分支。

![CASE-5](images/background_agent_send_followup.png)

### 后台 agent 完成通知

如下图，后台 Explore agent 完成后通过主循环展示通知和结果摘要，并把完整结果保存到本地文件，避免主上下文被过长结果污染。

![CASE-5](images/background_agent_followup_result.png)

### 验证结论

这组测试确认了后台 agent 链路：

- 后台 agent 不阻塞主 REPL。
- `async_launched` 会返回可追踪的 `agent_id`。
- 后台完成后会通过 queue 通知主循环。
- follow-up 会复用同一个 agent 的 transcript，而不是丢失上下文。
- 长结果会写入本地文件，主屏只展示摘要。
