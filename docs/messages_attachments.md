# Message + Attachments 增强

本文档描述消息规范化、工具结果存储和附件处理系统。

---

## 涉及文件

```
messages.py             ← 消息创建与规范化（增强）
tool_result_storage.py  ← 大型工具结果磁盘存储（新建）
attachments.py          ← 文件附件处理（新建）
api.py                  ← 集成工具结果处理
cli.py                  ← 集成附件处理
```

---

## messages.py 增强

对应 TS: `utils/messages.ts`（5512 行），Python 简化版 ~150 行。

### 新增函数

| 函数 | 说明 |
|------|------|
| `create_user_message(content, tool_results)` | 支持字符串、content blocks、tool_result |
| `create_assistant_message(content)` | 创建 assistant 文本消息 |
| `create_tool_use_assistant_message(text, blocks)` | 创建含 tool_use 的 assistant 消息 |
| `create_tool_result_message(results)` | 创建 tool_result 的 user 消息 |
| `normalize_messages_for_api(messages)` | 规范化：合并同角色消息、过滤空消息 |
| `messages_to_text(messages)` | 消息列表转纯文本（用于压缩摘要） |

### 消息规范化

`normalize_messages_for_api()` 确保 API 调用时消息格式正确：
1. 过滤 system 消息（通过 system 参数传递）
2. 合并连续相同角色的消息（如两条 user → 合并 content）
3. 过滤空消息

---

## tool_result_storage.py

对应 TS: `utils/toolResultStorage.ts`（1040 行），Python 简化版 ~150 行。

### 问题

大型工具结果（如 grep 匹配几千行、bash 输出大量日志）会快速消耗上下文窗口。

### 解决方案

```
工具结果（50K+ 字符）
  │
  ▼
should_persist() → YES
  │
  ▼
persist_tool_result()
  ├─ 完整内容写入 .claude/tool-results/<id>.txt
  └─ 返回 {filepath, preview, original_size}
  │
  ▼
build_large_result_message()
  └─ 上下文中只保留：
     - 前 2000 字符预览
     - <persisted-output> 标签（含文件路径引用）
     - 模型可通过 read_file 查看完整内容
```

### 阈值

| 参数 | 值 | 说明 |
|------|---|------|
| `PERSIST_THRESHOLD` | 50,000 字符 | 超过此大小持久化到磁盘 |
| `PREVIEW_SIZE` | 2,000 字符 | 预览保留的字符数 |
| `TRUNCATE_SIZE` | 10,000 字符 | 非持久化的截断大小 |

### 集成位置

在 `api.py` 的 `_execute_tools_concurrent()` 中，工具执行后、PostToolUse Hook 前：

```python
result_text = process_tool_result(result_text, tb["id"], tb["name"])
```

---

## attachments.py

对应 TS: `utils/attachments.ts`（3997 行），Python 简化版 ~180 行。

### 支持的附件类型

| 类型 | 处理方式 | 支持的扩展名 |
|------|---------|-------------|
| 文本文件 | 读取内容注入消息 | .py .js .ts .md .json .yaml 等 30+ 种 |
| 图片 | base64 编码 | .png .jpg .jpeg .gif .webp |

### @文件引用

用户输入中通过 `@path/to/file` 引用文件：

```
"请帮我分析 @src/main.py 的代码质量"
```

`process_attachments()` 自动：
1. 提取 `src/main.py` 路径
2. 读取文件内容
3. 作为 content block 注入消息

### 集成位置

在 `cli.py` 的交互循环中，用户输入后、创建消息前：

```python
attachment_blocks = process_attachments(effective_input)
if attachment_blocks:
    content_blocks = [{"type": "text", "text": effective_input}] + attachment_blocks
    messages.append(create_user_message(content_blocks))
```

---

## 与 TS 版的差异

| 特性 | TS 版 | Python 版 |
|------|-------|----------|
| 消息规范化 | ✅ 完整 | ✅ 核心（角色合并、过滤） |
| Tool result 持久化 | ✅ 完整 | ✅ 核心（磁盘存储 + 预览） |
| Tool result 预算管理 | ✅ | ❌ |
| 文件附件 | ✅ 完整 | ✅ 基础（@引用） |
| 图片附件 | ✅ | ✅ |
| PDF 附件 | ✅ | ❌ |
| MCP 资源附件 | ✅ | ❌ |
| 内存文件附件 | ✅ | ❌ |
| 目录遍历附件 | ✅ | ❌ |
