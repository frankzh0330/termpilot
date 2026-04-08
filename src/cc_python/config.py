"""配置管理。

对应 TS: utils/config.ts + utils/managedEnv.ts

核心机制（和 TS 完全一致）：
1. 读取 ~/.claude/settings.json
2. 其中的 env 字段包含环境变量（如 ANTHROPIC_BASE_URL、ANTHROPIC_API_KEY）
3. 将 env 注入到 os.environ
4. 后续创建 API 客户端时自动使用这些环境变量

这样只需改 settings.json 就能切换 API provider。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _get_settings_path() -> Path:
    """对应 TS 中的 settings.json 路径。"""
    return Path.home() / ".claude" / "settings.json"


def get_settings() -> dict[str, Any]:
    """读取 settings.json 配置。

    对应 TS 中读取 settings.json 的逻辑。
    settings.json 示例:
    {
      "env": {
        "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
        "ANTHROPIC_API_KEY": "xxx.xxx",
        "ANTHROPIC_MODEL": "glm-4-flash"
      }
    }
    """
    settings_path = _get_settings_path()
    if not settings_path.exists():
        return {}
    try:
        return json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def get_settings_env() -> dict[str, str]:
    """从 settings.json 中读取 env 字段。

    对应 TS utils/managedEnv.ts：
    从 settings.json 的 env 字段读取环境变量配置。
    """
    settings = get_settings()
    env: dict[str, str] = {}
    settings_env = settings.get("env", {})
    if isinstance(settings_env, dict):
        for key, value in settings_env.items():
            if isinstance(value, str):
                env[key] = value
    return env


def apply_settings_env() -> None:
    """将 settings.json 中的 env 注入到 os.environ。

    对应 TS utils/managedEnv.ts applySafeConfigEnvironmentVariables()。

    把 settings.json 中的 env 字段写入 os.environ，
    使得后续创建 API 客户端时自动使用。
    这就是"只改 settings.json 就能切换 provider"的核心机制。
    """
    settings_env = get_settings_env()
    os.environ.update(settings_env)


def get_effective_api_key() -> str | None:
    """获取有效的 API Key。

    对应 TS utils/auth.ts getAnthropicApiKey() +
    services/api/client.ts configureApiKeyHeaders()。

    TS 中 key 来源优先级：
    1. ANTHROPIC_API_KEY 环境变量
    2. ANTHROPIC_AUTH_TOKEN（Bearer token，Claude Code 用这个）
    3. apiKeyHelper（外部命令获取）
    4. OAuth token

    Python 简化版：支持 ANTHROPIC_API_KEY、ANTHROPIC_AUTH_TOKEN、ZHIPU_API_KEY。
    """
    env = get_settings_env()
    return (
        os.environ.get("ANTHROPIC_API_KEY")
        or env.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or env.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ZHIPU_API_KEY")
        or env.get("ZHIPU_API_KEY")
    )


def get_effective_base_url() -> str | None:
    """获取有效的 API Base URL。

    对应 TS 中通过 ANTHROPIC_BASE_URL 环境变量配置第三方 provider。
    智谱的 URL: https://open.bigmodel.cn/api/paas/v4

    优先级：
    1. 环境变量 ANTHROPIC_BASE_URL
    2. settings.json 中的 env.ANTHROPIC_BASE_URL
    """
    return (
        os.environ.get("ANTHROPIC_BASE_URL")
        or get_settings_env().get("ANTHROPIC_BASE_URL")
    )


def get_effective_model(default: str = "claude-sonnet-4-20250514") -> str:
    """获取默认模型。

    优先级：
    1. 环境变量 ANTHROPIC_MODEL
    2. settings.json 中的 env.ANTHROPIC_MODEL
    3. 传入的 default 参数
    """
    return (
        os.environ.get("ANTHROPIC_MODEL")
        or get_settings_env().get("ANTHROPIC_MODEL")
        or default
    )
