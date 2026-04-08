# cc_python 开发计划

## 实现顺序

### 1. 工具调用（Tool Use）— 当前阶段
让模型能够调用工具（读写文件、执行命令），这是 Claude Code 的核心能力。

#### 1.1 工具定义框架
- 新建 `src/cc_python/tools/base.py`：定义 Tool 基类/协议
  - `name`: 工具名称
  - `description`: 工具描述（传给模型的）
  - `input_schema`: JSON Schema 格式的参数定义
  - `call(input) -> str`: 执行工具，返回结果文本
- 对应 TS: `Tool.ts` 中的 `Tool` 类型定义（简化版，去掉权限/UI/渲染等）

#### 1.2 实现基础工具
- 新建 `src/cc_python/tools/read_file.py`：文件读取工具
  - 参数: `file_path`, `offset`, `limit`
  - 返回文件内容（带行号）
- 新建 `src/cc_python/tools/write_file.py`：文件写入工具
  - 参数: `file_path`, `content`
  - 写入文件并返回确认
- 新建 `src/cc_python/tools/edit_file.py`：文件编辑工具
  - 参数: `file_path`, `old_string`, `new_string`
  - 精确字符串替换
- 新建 `src/cc_python/tools/bash.py`：命令执行工具
  - 参数: `command`
  - 执行 shell 命令并返回输出
- 新建 `src/cc_python/tools/glob.py`：文件搜索工具
  - 参数: `pattern`
  - glob 模式匹配文件
- 新建 `src/cc_python/tools/grep.py`：内容搜索工具
  - 参数: `pattern`, `path`
  - ripgrep 风格搜索

#### 1.3 工具注册
- 新建 `src/cc_python/tools/__init__.py`：注册所有工具
  - `get_all_tools() -> list[Tool]`
  - `get_tools_schema(tools) -> list[dict]`：生成 Anthropic API 的 tools 参数
  - 对应 TS: `tools.ts` 中的 `getAllBaseTools()` 和 `getTools()`

#### 1.4 工具调用循环（核心）
- 修改 `src/cc_python/api.py`：
  - `query_model_streaming` 支持接收 `tools` 参数
  - 流式响应中检测 `tool_use` content block
  - 执行工具，将结果作为 `tool_result` 回传 API
  - 循环直到模型返回纯文本（不再调用工具）
- 对应 TS: `query.ts` 中的主循环（约第 554-863 行）
  - 关键流程: API 响应 → 检测 tool_use block → 执行工具 → tool_result → 再次调用 API

#### 1.5 消息格式扩展
- 修改 `src/cc_python/messages.py`：
  - 支持 `tool_use` 和 `tool_result` 消息类型
  - 对应 TS: `utils/messages.ts` 中的消息规范化

---

### 2. 权限系统
- 工具执行前询问用户确认
- 对应 TS: `hooks/useCanUseTool.ts` + `utils/permissions/`

### 3. System Prompt 完善
- 补全完整的系统指令
- 对应 TS: `utils/systemPrompt.ts`

### 4. 消息历史持久化
- 对话保存/恢复，支持 resume
- 对应 TS: `utils/conversation.ts`

---

## TS 源码关键对应关系

| Python (待实现) | TS 源码 | 功能 |
|---|---|---|
| `tools/base.py` | `Tool.ts` | 工具基类定义 |
| `tools/*.py` | `tools/*Tool/` | 具体工具实现 |
| `tools/__init__.py` | `tools.ts` | 工具注册和获取 |
| `api.py` (修改) | `query.ts` + `services/api/claude.ts` | 工具调用循环 |
| `messages.py` (修改) | `utils/messages.ts` | 消息格式 |
