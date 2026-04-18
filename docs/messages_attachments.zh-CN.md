# Messages、Attachments 与大型工具结果

[English](messages_attachments.md) | [简体中文](messages_attachments.zh-CN.md)

本文档说明当前消息辅助、附件处理和超大工具结果处理逻辑。

## 涉及模块

```text
messages.py             → 消息构造与规范化辅助
attachments.py          → 本地附件处理
tool_result_storage.py  → 超大工具输出的持久化与截断
api.py                  → 集成工具结果存储/截断逻辑
cli.py                  → 集成附件处理
```

## `messages.py`

当前消息辅助模块主要负责为模型构造一致的消息结构。

核心职责：

- 创建 user / assistant 消息
- 将消息内容规范化为 API 友好的格式
- 支持工具调用循环所需的 tool-use / tool-result 消息形态

## `attachments.py`

附件会在用户 prompt 发送给模型前完成处理。

当前职责包括：

- 将引用的本地文件展开为消息内容
- 以安全格式将附件内容追加到 prompt 中

## `tool_result_storage.py`

大型工具输出很容易快速吃掉上下文窗口，因此当前子系统会：

- 判断工具结果是否需要持久化
- 将超大输出写入磁盘
- 在当前会话里只保留预览型替代消息
- 对“不至于持久化但仍然偏大”的结果做截断

## 为什么需要这一层

如果没有它：

- `grep` 输出很容易占满 transcript
- 冗长的 shell 日志会挤掉推理上下文
- 重复工具调用会让长会话中的模型效果越来越差

## 当前策略

当前实现采用基于阈值的分层处理：

- 小输出：直接内联
- 中等输出：内联但截断
- 超大输出：持久化到磁盘，并在上下文中只保留预览和引用

它会与 `compact.py` 配合工作，后者在需要时还会继续清理更早的工具结果。
