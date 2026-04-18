# 编码规范

[English](conventions.md) | [简体中文](conventions.zh-CN.md)

本文档描述 `termpilot` 中主要的命名规则与文件组织约定。

## 命名

| 项目 | 风格 | 示例 |
|------|------|------|
| 模块 | `snake_case` | `read_file.py`、`tool_result_storage.py` |
| 类 | `PascalCase` | `PermissionMode`、`HookResult` |
| 函数 | `snake_case` | `check_permission()`、`build_system_prompt()` |
| 常量 | `UPPER_SNAKE_CASE` | `SAFE_TOOLS`、`MAX_CONCURRENT_TOOLS` |
| 私有辅助函数 | `_` 前缀 | `_match_rule()`、`_build_hook_input()` |
| dataclass 字段 | `snake_case` | `tool_name`、`exit_code` |

## 文件组织

- 尽量一个概念一个模块
- 顶层运行时模块放在 `src/termpilot/`
- 具体工具实现放在 `src/termpilot/tools/`
- MCP 集成放在 `src/termpilot/mcp/`
- 文档放在 `docs/`
- 小型项目脚本放在 `scripts/`

## 典型模块结构

大多数模块大致遵循：

1. 模块 docstring，说明对应的 TypeScript 源码
2. `from __future__ import annotations`
3. 标准库 imports
4. 第三方 imports
5. 项目内 imports
6. 常量
7. 数据结构 / enum / dataclass
8. 公共函数与辅助函数

## Import 顺序

推荐顺序：

1. `from __future__ import annotations`
2. 标准库
3. 第三方包
4. 项目内 imports

## 设计约定

- 工具实现尽量保持独立，通过 `Tool` protocol 接口对齐，而不是继承统一基类。
- 权限逻辑集中在 `permissions.py` / `api.py`，不要塞进工具内部。
- hook 执行逻辑集中在 `hooks.py`。
- 优先使用显式 helper，而不是深层继承体系。
- 修改已有模块时，优先遵循该模块现有风格。
