# System Prompt Sections

[English](system_prompt_sections.md) | [简体中文](system_prompt_sections.zh-CN.md)

本文档说明 `context.py` 中 `build_system_prompt()` 的结构。

## 概览

system prompt 由静态 sections 和动态 sections 共同拼装而成。相比“固定有多少节”，更重要的设计原则是：

- 稳定的核心指令写成常量
- 依赖运行时状态的指令通过 helper 动态生成

## 静态核心

静态核心主要覆盖：

- 角色定位与安全边界
- 系统行为与渲染假设
- 软件工程任务执行方式
- 工具使用规范
- 风险操作控制
- 语气与输出效率

这些 section 共同定义模型的基础运行规则。

## 动态 Sections

动态 section 会基于运行时状态生成，例如：

- 根据已启用工具生成 session-specific guidance
- memory 指导与 memory index 内容
- 当前工作目录、平台、shell、日期、git 状态等环境信息
- 当设置了语言参数时的输出语言偏好
- MCP server 暴露的 instructions
- 关于记录重要工具结果的提醒

## `context.py` 中的重要辅助函数

- `get_system_context()`
- `get_git_status()`
- `get_session_guidance_section()`
- `get_language_section()`
- `get_mcp_instructions_section()`
- `load_memory_prompt()`
- `build_system_prompt()`

## Memory 集成

memory 子系统并不是简单把旧笔记塞进 prompt，而是会注入：

- memory 类型说明
- 何时该保存、何时不该保存
- memory 文件结构约束
- 当前 `MEMORY.md` 索引内容（如果存在）

## MCP 集成

当 MCP server 提供 instructions 时，这些内容会作为独立 prompt section 注入，让模型遵守 server 侧的使用约束。

## 设计目标

prompt builder 被刻意设计成可组合的结构：

- 每个 section 都能独立修改
- 运行时依赖保持显式
- 整体 prompt 可以演进，而不会退化成一个超大的模板字符串
