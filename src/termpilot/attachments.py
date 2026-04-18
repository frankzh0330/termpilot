"""附件处理。

对应 TS: utils/attachments.ts（3997 行）
Python 简化版保留核心：文件附件读取（图片 base64、文本文件内容注入）。

支持的附件类型：
- 文本文件（.py, .js, .md, .txt 等）→ 作为文本注入消息
- 图片（.png, .jpg, .jpeg）→ base64 编码注入消息
- PDF → 文本提取（预留接口）

TS 版支持更丰富的附件：@文件引用、MCP 资源、图片粘贴、PDF 等。
Python 简化版仅支持路径引用（用户输入中包含文件路径时自动读取）。
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 支持的文本文件扩展名
TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt", ".scala",
    ".md", ".txt", ".rst", ".org", ".adoc",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".sh", ".bash", ".zsh", ".fish",
    ".html", ".css", ".scss", ".less",
    ".sql", ".graphql",
    ".dockerfile", ".makefile",
    ".gitignore", ".env", ".editorconfig",
    ".xml", ".svg",
    ".log", ".csv",
}

# 支持的图片扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# 图片最大大小（10MB）
IMAGE_MAX_SIZE = 10 * 1024 * 1024

# 文本文件最大读取大小（1MB）
TEXT_MAX_SIZE = 1024 * 1024


def is_text_file(path: str | Path) -> bool:
    """判断是否为可读的文本文件。"""
    ext = Path(path).suffix.lower()
    return ext in TEXT_EXTENSIONS


def is_image_file(path: str | Path) -> bool:
    """判断是否为图片文件。"""
    ext = Path(path).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def read_file_as_attachment(path: str | Path) -> dict[str, Any] | None:
    """读取文件作为附件。

    对应 TS 中的 generateFileAttachment()。

    返回 Anthropic API 的 content block 格式：
    - 文本文件 → {"type": "text", "text": "..."}
    - 图片文件 → {"type": "image", "source": {"type": "base64", ...}}
    """
    filepath = Path(path)

    if not filepath.exists():
        return None

    if not filepath.is_file():
        return None

    if is_image_file(filepath):
        return _read_image(filepath)
    elif is_text_file(filepath):
        return _read_text(filepath)

    return None


def _read_text(filepath: Path) -> dict[str, Any] | None:
    """读取文本文件。"""
    try:
        size = filepath.stat().st_size
        if size > TEXT_MAX_SIZE:
            return {
                "type": "text",
                "text": f"[File too large: {filepath} ({size} bytes, max {TEXT_MAX_SIZE})]",
            }

        content = filepath.read_text(encoding="utf-8", errors="replace")
        rel_path = filepath.name
        return {
            "type": "text",
            "text": f"--- {rel_path} ---\n{content}\n--- end of {rel_path} ---",
        }
    except OSError as e:
        logger.warning("Failed to read text file %s: %s", filepath, e)
        return None


def _read_image(filepath: Path) -> dict[str, Any] | None:
    """读取图片文件为 base64 编码。"""
    try:
        size = filepath.stat().st_size
        if size > IMAGE_MAX_SIZE:
            return {
                "type": "text",
                "text": f"[Image too large: {filepath} ({size} bytes, max {IMAGE_MAX_SIZE})]",
            }

        data = filepath.read_bytes()
        media_type = mimetypes.guess_type(str(filepath))[0] or "image/png"
        b64 = base64.standard_b64encode(data).decode("ascii")

        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64,
            },
        }
    except OSError as e:
        logger.warning("Failed to read image %s: %s", filepath, e)
        return None


def extract_file_paths(text: str) -> list[str]:
    """从用户输入中提取文件路径引用。

    对应 TS extractAtMentionedFiles()。

    识别模式：
    - @path/to/file — at 引用
    - 绝对路径 /path/to/file
    - 相对路径 ./path/to/file 或 path/to/file.ext
    """
    import re

    paths = []

    # @引用模式
    at_pattern = r'@(/?[^\s@]+\.[a-zA-Z0-9]+)'
    for match in re.finditer(at_pattern, text):
        path = match.group(1)
        if Path(path).exists():
            paths.append(path)

    return paths


def process_attachments(user_input: str) -> list[dict[str, Any]]:
    """处理用户输入中的文件附件。

    对应 TS getAttachments() 中的文件引用处理。

    1. 从输入中提取文件路径
    2. 读取每个文件作为附件
    3. 返回 content blocks 列表
    """
    file_paths = extract_file_paths(user_input)
    if not file_paths:
        return []

    blocks = []
    for path in file_paths:
        attachment = read_file_as_attachment(path)
        if attachment:
            blocks.append(attachment)

    return blocks
