# 黄金原则

[English](golden-rules.md) | [简体中文](golden-rules.zh-CN.md)

这些是当前代码库中最重要、最稳定的实现原则。

## 1. 工具通过 `Tool` protocol 对齐

`tools/*.py` 中的具体工具实现 `tools/base.py` 里的 `Tool` protocol。

原因：

- 让工具之间保持低耦合
- 避免深层继承
- 便于在 `tools/__init__.py` 中统一注册

## 2. 权限策略不要写进工具内部

工具方法只负责执行，不负责决定“是否允许执行”。

权限链路属于：

- `permissions.py`
- `api.py`
- `cli.py` 中的用户确认 UI

## 3. Hooks 是独立子系统

hook 配置加载与子进程执行都放在 `hooks.py`。`api.py` 和 `cli.py` 只消费 hook 结果，不重复实现 hook 行为。

## 4. System Prompt section 要模块化

`context.py` 采用“静态 section 常量 + 小型动态 section builder”的结构。新增 section 时应保持局部、可组合，而不是把逻辑堆成一个巨大函数。

## 5. 工具调用循环必须集中管理

主编排逻辑放在 `api.py`：

- 流式接收模型输出
- 收集工具调用
- 执行 hooks
- 权限检查
- 执行工具
- 回灌工具结果
- 循环直到结束

不要把这条主链拆散到多个层里。

## 6. 先用确定性的本地逻辑

如果一个问题可以通过本地变换、清理、校验或截断解决，就优先这样做，再考虑增加模型调用或外部依赖。

例子：

- 压缩前先做本地 token 估算
- 超大工具结果先本地持久化/截断
- 文件写入前先做路径安全校验

## 7. 长期状态要显式走现有子系统

不要发明临时持久化方案，优先使用已有机制：

- session → `session.py`
- undo snapshots → `undo.py`
- memory prompt / index → `context.py`
- 大型工具输出 → `tool_result_storage.py`

## 8. 保持“分阶段重写”思路

这个项目在子系统层面对齐 TypeScript 版，但会有意识地简化很多细节。优先保持行为一致和代码清晰，而不是逐行复制复杂度。
