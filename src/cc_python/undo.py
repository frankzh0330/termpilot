"""Undo/回退系统 — 文件修改前的快照保存与恢复。

对应 TS: utils/diff.ts（~5K 行，TS 版有完整的 patch/diff 系统）

Python 版持久化快照：
- 快照保存到磁盘（~/.claude/undo/），重启后仍可回退
- 每个 session 对应一个快照文件（JSONL 格式）
- 记录文件路径 + 修改前内容 + 时间戳
- write_file/edit_file 修改前自动保存
- /undo 命令弹出最近的快照并恢复文件内容

快照格式（JSONL 每行一个 JSON）：
{
  "path": "/abs/file.py",
  "content": "修改前的完整内容（null 表示文件不存在）",
  "timestamp": "2026-04-15T10:30:00Z",
  "operation": "write_file" | "edit_file",
  "old_string": "被替换的文本（仅 edit_file）",
  "new_string": "替换后的文本（仅 edit_file）"
}
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SNAPSHOTS = 50

# 当前 session 的内存栈（同时写入磁盘）
_undo_stack: list[dict[str, Any]] = []

# 快照文件路径（懒初始化）
_snapshot_file: Path | None = None


def _get_snapshot_dir() -> Path:
    """获取快照存储目录。"""
    config_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
    return config_home / "undo"


def _get_snapshot_file() -> Path:
    """获取当前 session 的快照文件路径。"""
    global _snapshot_file
    if _snapshot_file is None:
        snap_dir = _get_snapshot_dir()
        snap_dir.mkdir(parents=True, exist_ok=True)
        # 用 PID 区分不同进程的快照
        _snapshot_file = snap_dir / f"session-{os.getpid()}.jsonl"
    return _snapshot_file


def init_undo(session_id: str | None = None) -> None:
    """初始化 undo 系统。可在 session 启动时调用。

    Args:
        session_id: 可选的 session ID，用于快照文件命名。
    """
    global _snapshot_file, _undo_stack
    snap_dir = _get_snapshot_dir()
    snap_dir.mkdir(parents=True, exist_ok=True)

    if session_id:
        _snapshot_file = snap_dir / f"session-{session_id[:8]}.jsonl"
    else:
        _snapshot_file = snap_dir / f"session-{os.getpid()}.jsonl"

    # 清空内存栈
    _undo_stack.clear()
    logger.debug("undo initialized: %s", _snapshot_file)


def save_snapshot(
        file_path: str,
        operation: str = "write_file",
        old_string: str | None = None,
        new_string: str | None = None,
) -> None:
    """修改前调用：读取当前文件内容并持久化快照。

    Args:
        file_path: 被修改的文件路径
        operation: 操作类型 "write_file" 或 "edit_file"
        old_string: edit_file 的替换文本（用于精细描述）
        new_string: edit_file 的新文本
    """
    path = Path(file_path).expanduser()

    if path.exists():
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("save_snapshot: cannot read %s: %s", file_path, e)
            content = None
    else:
        content = None  # 文件不存在（新建场景）

    snapshot: dict[str, Any] = {
        "path": str(path),
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
    }

    # edit_file 时额外记录替换信息
    if old_string is not None:
        snapshot["old_string"] = old_string
    if new_string is not None:
        snapshot["new_string"] = new_string

    # 写入内存栈
    _undo_stack.append(snapshot)

    # 持久化到磁盘
    _persist_snapshot(snapshot)

    logger.debug("snapshot saved: %s op=%s (exists=%s, content_len=%s)",
                 file_path, operation, path.exists(),
                 len(content) if content is not None else "N/A")

    # 防止内存膨胀
    if len(_undo_stack) > _MAX_SNAPSHOTS:
        removed = _undo_stack.pop(0)
        logger.debug("snapshot evicted (stack full): %s", removed["path"])


def _persist_snapshot(snapshot: dict[str, Any]) -> None:
    """将单个快照追加写入磁盘文件。"""
    try:
        snap_file = _get_snapshot_file()
        line = json.dumps(snapshot, ensure_ascii=False)
        with open(snap_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        logger.debug("persist snapshot failed: %s", e)


def pop_snapshot() -> dict[str, Any] | None:
    """弹出最近的快照。返回 {"path": ..., "content": ...} 或 None。"""
    if not _undo_stack:
        # 尝试从磁盘加载
        _load_from_disk()
        if not _undo_stack:
            return None
    snapshot = _undo_stack.pop()
    # 同步磁盘：重写为剩余快照
    _rewrite_disk()
    return snapshot


def has_snapshots() -> bool:
    """是否有可回退的快照。"""
    if _undo_stack:
        return True
    # 检查磁盘
    return _disk_snapshot_count() > 0


def get_snapshot_count() -> int:
    """当前快照栈深度。"""
    return len(_undo_stack) or _disk_snapshot_count()


def clear_snapshots() -> None:
    """清空快照栈和磁盘文件。"""
    _undo_stack.clear()
    try:
        snap_file = _get_snapshot_file()
        if snap_file.exists():
            snap_file.unlink()
    except OSError:
        pass


def _load_from_disk() -> None:
    """从磁盘加载快照到内存（仅在内存为空时调用）。"""
    try:
        snap_file = _get_snapshot_file()
        if not snap_file.exists():
            return
        with open(snap_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    _undo_stack.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        logger.debug("loaded %d snapshots from disk", len(_undo_stack))
    except OSError as e:
        logger.debug("load from disk failed: %s", e)


def _rewrite_disk() -> None:
    """将当前内存栈重写到磁盘（pop 后调用）。"""
    try:
        snap_file = _get_snapshot_file()
        with open(snap_file, "w", encoding="utf-8") as f:
            for snapshot in _undo_stack:
                f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.debug("rewrite disk failed: %s", e)


def _disk_snapshot_count() -> int:
    """磁盘上的快照数量。"""
    try:
        snap_file = _get_snapshot_file()
        if not snap_file.exists():
            return 0
        count = 0
        with open(snap_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
    except OSError:
        return 0


def cleanup_stale_snapshots(max_age_hours: int = 24) -> int:
    """清理过期的快照文件。

    删除超过 max_age_hours 的快照文件。
    返回删除的文件数。
    """
    snap_dir = _get_snapshot_dir()
    if not snap_dir.exists():
        return 0

    now = time.time()
    max_age_seconds = max_age_hours * 3600
    deleted = 0

    for snap_file in snap_dir.glob("session-*.jsonl"):
        try:
            age = now - snap_file.stat().st_mtime
            if age > max_age_seconds:
                snap_file.unlink()
                deleted += 1
                logger.debug("cleaned stale snapshot: %s (age=%.0fh)", snap_file.name, age / 3600)
        except OSError:
            pass

    if deleted:
        logger.debug("cleaned %d stale snapshot files", deleted)
    return deleted
