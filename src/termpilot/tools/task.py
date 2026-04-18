"""Task 工具组（任务管理）。

对应 TS: tools/TaskCreateTool/ + TaskUpdateTool/ + TaskListTool/ + TaskGetTool/（~1200 行）
Python 简化版合并为单文件，使用内存存储。

提供 4 个工具：
- TaskCreate: 创建任务
- TaskUpdate: 更新任务状态
- TaskList: 列出所有任务
- TaskGet: 获取单个任务详情
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any


# ── 数据模型 ──────────────────────────────────────────

@dataclass
class Task:
    """任务数据。"""
    id: str
    subject: str
    description: str = ""
    status: str = "pending"  # pending | in_progress | completed | deleted
    owner: str = ""
    active_form: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# 全局任务存储
_tasks: dict[str, Task] = {}
_task_counter = 0


def _next_task_id() -> str:
    global _task_counter
    _task_counter += 1
    return str(_task_counter)


def _reset_tasks() -> None:
    """重置任务存储（用于测试）。"""
    global _tasks, _task_counter
    _tasks.clear()
    _task_counter = 0


# ── TaskCreate ────────────────────────────────────────

class TaskCreateTool:
    """创建任务。"""

    @property
    def name(self) -> str:
        return "task_create"

    @property
    def description(self) -> str:
        return "Create a structured task for tracking progress on multi-step work."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "A brief title for the task (imperative form, e.g. 'Fix authentication bug').",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description of what needs to be done.",
                },
                "activeForm": {
                    "type": "string",
                    "description": "Present continuous form shown when task is in_progress (e.g. 'Running tests').",
                },
            },
            "required": ["subject", "description"],
        }

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def call(self, **kwargs: Any) -> str:
        subject = kwargs.get("subject", "")
        description = kwargs.get("description", "")
        active_form = kwargs.get("activeForm", "")

        if not subject:
            return "Error: subject is required."

        task = Task(
            id=_next_task_id(),
            subject=subject,
            description=description,
            active_form=active_form,
        )
        _tasks[task.id] = task

        return json.dumps({"task": {"id": task.id, "subject": task.subject}}, ensure_ascii=False)


# ── TaskUpdate ────────────────────────────────────────

class TaskUpdateTool:
    """更新任务状态。"""

    @property
    def name(self) -> str:
        return "task_update"

    @property
    def description(self) -> str:
        return "Update a task's status, subject, or description."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "taskId": {
                    "type": "string",
                    "description": "The ID of the task to update.",
                },
                "status": {
                    "type": "string",
                    "description": "New status: 'pending', 'in_progress', 'completed', or 'deleted'.",
                    "enum": ["pending", "in_progress", "completed", "deleted"],
                },
                "subject": {
                    "type": "string",
                    "description": "New title for the task.",
                },
                "description": {
                    "type": "string",
                    "description": "New description.",
                },
            },
            "required": ["taskId"],
        }

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def call(self, **kwargs: Any) -> str:
        task_id = kwargs.get("taskId", "")
        task = _tasks.get(task_id)

        if not task:
            return f"Error: Task '{task_id}' not found."

        if "status" in kwargs:
            task.status = kwargs["status"]
        if "subject" in kwargs:
            task.subject = kwargs["subject"]
        if "description" in kwargs:
            task.description = kwargs["description"]

        task.updated_at = time.time()

        return json.dumps({"task": {"id": task.id, "subject": task.subject, "status": task.status}}, ensure_ascii=False)


# ── TaskList ──────────────────────────────────────────

class TaskListTool:
    """列出所有任务。"""

    @property
    def name(self) -> str:
        return "task_list"

    @property
    def description(self) -> str:
        return "List all tasks with their current status."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def call(self, **kwargs: Any) -> str:
        if not _tasks:
            return "No tasks."

        lines = []
        for task in _tasks.values():
            if task.status == "deleted":
                continue
            status_icon = {"pending": " ", "in_progress": "*", "completed": "x"}.get(task.status, "?")
            lines.append(f"[{status_icon}] {task.id}: {task.subject} ({task.status})")
            if task.description:
                lines.append(f"    {task.description[:100]}")

        return "\n".join(lines)


# ── TaskGet ───────────────────────────────────────────

class TaskGetTool:
    """获取单个任务详情。"""

    @property
    def name(self) -> str:
        return "task_get"

    @property
    def description(self) -> str:
        return "Get full details of a specific task by ID."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "taskId": {
                    "type": "string",
                    "description": "The ID of the task to retrieve.",
                },
            },
            "required": ["taskId"],
        }

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def call(self, **kwargs: Any) -> str:
        task_id = kwargs.get("taskId", "")
        task = _tasks.get(task_id)

        if not task:
            return f"Error: Task '{task_id}' not found."

        return json.dumps(task.to_dict(), ensure_ascii=False, indent=2)
