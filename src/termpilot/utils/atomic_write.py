"""原子文件写入（修复 P0-2：非原子文件写入）。

进程崩溃或断电时，直接 ``path.write_text(...)`` 可能把文件截断为空或
写入一半，导致 settings / 任务状态 / 权限规则丢失。这里参照 Claude Code
的 writeFileSyncAndFlush 实现：临时文件 + fsync + 原子 rename，POSIX
保证 rename 要么成功要么不发生。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: str) -> None:
    """以原子方式写入文本文件（UTF-8）。

    流程：同目录临时文件 → 写入 + fsync → 保留原文件权限 → rename 替换。
    任一步失败时清理临时文件，原文件不受影响。
    """
    dir_path = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=dir_path, prefix=f".{path.name}.tmp.")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        # 保留原文件权限，避免 settings 等文件权限被 mkstemp 重置
        try:
            os.chmod(tmp_path, path.stat().st_mode)
        except FileNotFoundError:
            pass  # 新文件，保持 mkstemp 的默认权限
        os.replace(tmp_path, path)  # POSIX 原子替换
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
