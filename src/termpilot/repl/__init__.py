"""交互式 REPL 子系统。

从 cli.py 的 _async_interactive（~530 行嵌套闭包）拆分而来，
对应 REFACTOR_CONTEXT.md 的目标结构：
- state.py          共享可变状态（替代 nonlocal 闭包变量）
- permissions_ui.py 权限提示交互
- stream_renderer.py 流式响应渲染
- input_handler.py  用户输入收集
- prompt_handler.py prompt / slash 命令 / 后台通知处理
- loop.py           主处理循环（dequeue → 分发）
cli.py 只保留组装（composition root）。
"""
