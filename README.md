# cc_python

Claude Code 的 Python 实现版本。一个运行在终端的 AI 编程助手，支持工具调用（读写文件、执行命令、搜索代码等），帮助你在命令行中完成软件开发任务。

> 本项目是 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 的 Python 重写，目前仍在逐步完善中。

## 功能特性

- **多 API Provider 支持** — 兼容 Anthropic、OpenAI 及兼容接口（如智谱 GLM）
- **流式响应** — 实时输出模型回复，支持 Markdown 渲染
- **工具调用循环** — 模型可自主调用工具，循环执行直到完成任务
- **并发工具执行** — 安全的工具（读文件、搜索）并行执行，不安全的工具串行执行
- **会话持久化** — 对话历史以 JSONL 格式保存，支持恢复历史会话
- **6 个核心工具** — 文件读写编辑、命令执行、文件搜索、内容搜索

## 已实现的工具

| 工具 | 名称 | 说明 | 并发安全 |
|------|------|------|----------|
| 读取文件 | `read_file` | 读取文件内容（带行号），支持 offset/limit | ✅ |
| 写入文件 | `write_file` | 创建或覆盖文件，自动创建父目录 | ❌ |
| 编辑文件 | `edit_file` | 精确字符串替换，支持 replace_all | ❌ |
| 执行命令 | `bash` | 执行 shell 命令，支持超时设置 | ❌ |
| 文件搜索 | `glob` | Glob 模式匹配搜索文件 | ✅ |
| 内容搜索 | `grep` | 正则表达式搜索文件内容 | ✅ |

## 快速开始

### 环境要求

- Python >= 3.12
- pip / uv

### 安装

```bash
# 克隆项目
git clone <repo-url> cc_python
cd cc_python

# 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
pip install -e .
```

### 配置

通过 `~/.claude/settings.json` 配置 API 密钥和 Provider：

```json
{
  "env": {
    "ANTHROPIC_API_KEY": "your-api-key-here"
  }
}
```

**切换为智谱 GLM：**

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
    "ANTHROPIC_API_KEY": "your-zhipu-api-key",
    "ANTHROPIC_MODEL": "glm-4-flash"
  }
}
```

**切换为 OpenAI 兼容接口：**

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.openai.com/v1",
    "ANTHROPIC_API_KEY": "your-openai-api-key",
    "ANTHROPIC_MODEL": "gpt-4o"
  }
}
```

> 也可以通过环境变量直接设置 `ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`，优先级高于 settings.json。

### 运行

```bash
# 交互模式 — 进入 REPL 对话
python -m cc_python

# 单次提问模式 — 执行完自动退出
python -m cc_python -p "读取 main.py 的内容"

# 指定模型
python -m cc_python -m claude-sonnet-4-20250514

# 恢复上一次会话
python -m cc_python --resume

# 指定会话 ID 恢复
python -m cc_python -s <session-id>
```

**交互模式中的命令：**

| 命令 | 说明 |
|------|------|
| `/exit`、`/quit` | 退出程序 |
| `Ctrl+C` | 退出程序 |

## 项目结构

```
cc_python/
├── pyproject.toml              # 项目配置与依赖
├── plan.md                     # 开发计划
└── src/cc_python/
    ├── __init__.py
    ├── __main__.py             # python -m 入口
    ├── cli.py                  # CLI 主界面（Click + Rich）
    ├── api.py                  # API 调用 + 工具调用循环
    ├── config.py               # 配置管理（settings.json / 环境变量）
    ├── context.py              # 系统上下文（OS 信息、Git 状态、System Prompt）
    ├── messages.py             # 消息格式化
    ├── session.py              # 会话持久化（JSONL）
    └── tools/
        ├── __init__.py          # 工具注册
        ├── base.py             # Tool 协议定义
        ├── read_file.py        # 文件读取工具
        ├── write_file.py       # 文件写入工具
        ├── edit_file.py        # 文件编辑工具
        ├── bash.py             # 命令执行工具
        ├── glob_tool.py        # 文件搜索工具
        └── grep_tool.py        # 内容搜索工具
```

## 架构概览

```
用户输入
  │
  ▼
┌──────────┐    流式请求     ┌──────────────┐
│  cli.py  │ ──────────────► │   api.py     │
│  (REPL)  │                 │ (工具循环)    │
└──────────┘                 └──────┬───────┘
                                    │
                              ┌─────▼──────┐
                              │  API 响应   │
                              │ (流式事件)  │
                              └─────┬──────┘
                                    │
                         ┌──────────┼──────────┐
                         │ 纯文本    │          │ tool_use
                         ▼          │          ▼
                    渲染输出        │   ┌────────────────┐
                                   │   │ 并发执行工具    │
                                   │   │ (safe=并行,    │
                                   │   │  unsafe=串行)  │
                                   │   └───────┬────────┘
                                   │           │
                                   │     ┌─────▼─────┐
                                   │     │ tool_result │
                                   │     │ 回传 API    │
                                   │     └─────┬─────┘
                                   │           │
                                   └───────────┘
                                     (循环直到无 tool_use)
```

## 核心流程

1. **用户输入** → 构造消息 + System Prompt
2. **调用 API** → 流式接收响应（文本 + tool_use blocks）
3. **工具执行** → 按并发安全性分组，并行或串行执行
4. **结果回传** → tool_result 追加到消息，再次调用 API
5. **循环** → 重复步骤 2-4，直到模型返回纯文本（不再调用工具）
6. **渲染输出** → Markdown 格式显示最终回复

## 与 TypeScript 版的对应关系

| Python | TypeScript | 功能 |
|--------|-----------|------|
| `cli.py` | `main.tsx` + `entrypoints/cli.tsx` | CLI 入口和 REPL |
| `api.py` | `query.ts` + `services/api/claude.ts` | API 调用和工具循环 |
| `config.py` | `utils/config.ts` + `utils/managedEnv.ts` | 配置管理 |
| `context.py` | `utils/systemPrompt.ts` | 系统上下文和 Prompt |
| `session.py` | `utils/conversation.ts` | 会话持久化 |
| `tools/base.py` | `Tool.ts` | 工具基类定义 |
| `tools/*.py` | `tools/*Tool/` | 具体工具实现 |
| `tools/__init__.py` | `tools.ts` | 工具注册 |

## 开发计划

- [x] 工具定义框架（Tool 协议）
- [x] 6 个基础工具（Read/Write/Edit/Bash/Glob/Grep）
- [x] 工具注册与 API Schema 生成
- [x] 工具调用循环（并发执行 + 串行执行）
- [x] API 调用层（Anthropic + OpenAI 双格式）
- [x] CLI 界面（交互模式 + 单次模式）
- [x] 配置管理（settings.json + 环境变量）
- [x] 会话持久化（JSONL 存储 + 恢复）
- [ ] 权限系统（工具执行前用户确认）
- [ ] System Prompt 完善
- [ ] 消息历史持久化优化（支持 resume 细节）
- [ ] 更多工具（Web 搜索、Jupyter Notebook 等）

## 依赖

- [click](https://click.palletsprojects.com/) — CLI 框架
- [rich](https://rich.readthedocs.io/) — 终端渲染（Markdown、表格、面板）
- [anthropic](https://github.com/anthropics/anthropic-sdk-python) — Anthropic API SDK（可选，按需安装）
- [openai](https://github.com/openai/openai-python) — OpenAI API SDK（可选，使用兼容接口时需要）

## 许可证

MIT
