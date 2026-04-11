# cc_python

Claude Code 的 Python 实现版。一个运行在终端的 AI 编程助手，支持工具调用、权限系统和事件钩子。

> 本项目是 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 的 Python 重写，逐阶段实现中。

## 技术栈

- Python 3.12+ / asyncio
- click (CLI) + rich (终端渲染)
- anthropic / openai SDK（API 调用，按需安装）

## 项目结构

```
src/cc_python/
├── cli.py          # CLI 入口 + 权限 UI + hook dispatch + slash commands
├── api.py          # 工具调用循环 + 流式响应 + PreToolUse/PostToolUse hooks
├── context.py      # System Prompt 构建（13 个 section）
├── config.py       # 配置管理（settings.json + 环境变量）
├── hooks.py        # Hooks 系统（5 个事件，command 类型）
├── permissions.py  # 权限系统（4 种模式，8 步检查）
├── messages.py     # 消息格式化
├── session.py      # 会话持久化（JSONL）
├── skills.py       # Skills 系统（磁盘加载 + frontmatter 解析）
├── commands.py     # Slash Commands（解析 + 分派 + 7 个内置命令）
├── claudemd.py     # CLAUDE.md 加载
├── mcp/            # MCP 子包
│   ├── __init__.py # MCPManager（连接管理 + 工具收集）
│   ├── client.py   # MCP 客户端（JSON-RPC 通信）
│   ├── transport.py # 传输层（stdio/sse）
│   └── config.py   # MCP 配置读取
└── tools/          # 工具（6 核心 + MCP 动态 + Skill）
```

## 关键文档

| 文档 | 内容 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 模块分层、依赖方向、数据流 |
| [docs/golden-rules.md](docs/golden-rules.md) | 机械化的编码规则 |
| [docs/conventions.md](docs/conventions.md) | 命名、模式、文件组织规范 |
| [plan.md](plan.md) | 9 阶段开发计划 + TS 源码映射 |
| [docs/hooks.md](docs/hooks.md) | Hooks 系统详解 |
| [docs/claudemd.md](docs/claudemd.md) | CLAUDE.md 加载系统详解 |
| [docs/compact.md](docs/compact.md) | 上下文压缩系统详解 |
| [docs/mcp.md](docs/mcp.md) | MCP/Skills/Commands 详解 |
| [docs/system_prompt_sections.md](docs/system_prompt_sections.md) | System Prompt 13 个 section 详解 |

## 开发状态

| 阶段 | 状态 |
|------|------|
| 1. 工具调用框架 + 6 个工具 | ✅ |
| 2. System Prompt（13 sections） | ✅ |
| 3. 权限系统 | ✅ |
| 4. Hooks 系统 | ✅ |
| 5. CLAUDE.md 读取注入 | ✅ |
| 6. 上下文压缩 | ✅ |
| 7. Message + Attachments | ✅ |
| 8. 高级工具（Agent/Task/Plan） | 待实现 |
| 9. MCP + Skills + Commands | ✅ |

## TS 源码位置

TypeScript 原版源码在 `/Users/frank/Documents/source_code/claude_code`。每个 Python 模块的 docstring 都标注了对应的 TS 源码文件。开发时参照 TS 版逻辑，Python 版做精简重写。

## 运行

```bash
python -m cc_python              # 交互模式
python -m cc_python -p "问题"     # 单次模式
python -m cc_python --resume      # 恢复会话
python3 scripts/check.py          # 质量检查
```

## 配置

`~/.claude/settings.json`，支持 Anthropic / OpenAI / 智谱 GLM 等接口。详见 README.md。
