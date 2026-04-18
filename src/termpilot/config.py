"""配置管理。

对应 TS: utils/config.ts + utils/managedEnv.ts

核心机制：
1. 优先读取 ~/.termpilot/settings.json
2. 兼容读取旧的 ~/.claude/settings.json
3. 其中的 env 字段包含环境变量
4. 将 env 注入到 os.environ
5. 后续创建 API 客户端时自动使用这些环境变量

Python 版在此基础上额外支持显式 provider 选择：
- anthropic
- openai
- openai_compatible

并兼容常见第三方 OpenAI-compatible 平台的变量命名：
Zhipu GLM / DeepSeek / Qwen(DashScope) / Moonshot / SiliconFlow /
OpenRouter / Groq / Together / Fireworks / Ollama / vLLM 等。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_PROVIDER_ALIASES = {
    "anthropic": "anthropic",
    "claude": "anthropic",
    "openai": "openai",
    "gpt": "openai",
    "openai_compatible": "openai_compatible",
    "openai-compatible": "openai_compatible",
    "compatible": "openai_compatible",
    "custom": "openai_compatible",
    "zhipu": "openai_compatible",
    "glm": "openai_compatible",
    "deepseek": "openai_compatible",
    "qwen": "openai_compatible",
    "dashscope": "openai_compatible",
    "moonshot": "openai_compatible",
    "kimi": "openai_compatible",
    "siliconflow": "openai_compatible",
    "openrouter": "openai_compatible",
    "groq": "openai_compatible",
    "together": "openai_compatible",
    "fireworks": "openai_compatible",
    "ollama": "openai_compatible",
    "vllm": "openai_compatible",
}


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _normalize_provider(provider: str | None) -> str:
    if not provider:
        return "anthropic"
    return _PROVIDER_ALIASES.get(provider.strip().lower(), "openai_compatible")


def get_config_home() -> Path:
    """获取 TermPilot 配置根目录。

    优先级：
    1. TERMPILOT_CONFIG_DIR
    2. 兼容旧变量 CLAUDE_CONFIG_DIR
    3. ~/.termpilot
    """
    configured = _first_nonempty(
        os.environ.get("TERMPILOT_CONFIG_DIR"),
        os.environ.get("CLAUDE_CONFIG_DIR"),
    )
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".termpilot"


def _get_legacy_config_home() -> Path | None:
    """获取兼容读取用的旧配置目录。"""
    if os.environ.get("TERMPILOT_CONFIG_DIR") or os.environ.get("CLAUDE_CONFIG_DIR"):
        return None
    return Path.home() / ".claude"


def get_settings_write_path() -> Path:
    """获取 settings.json 的写入/展示路径。"""
    return get_config_home() / "settings.json"


def get_settings_path() -> Path:
    """获取 settings.json 的读取路径。

    默认使用 ~/.termpilot/settings.json。
    若该文件不存在，则兼容读取旧的 ~/.claude/settings.json。
    """
    primary = get_settings_write_path()
    if primary.exists():
        return primary

    legacy_home = _get_legacy_config_home()
    if legacy_home is not None:
        legacy = legacy_home / "settings.json"
        if legacy.exists():
            return legacy

    return primary


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
    settings_path = get_settings_path()
    if not settings_path.exists():
        logger.debug("settings.json not found at %s", settings_path)
        return {}
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        logger.debug("loaded settings.json: %d keys (%s)", len(data), ", ".join(data.keys()))
        return data
    except (json.JSONDecodeError, OSError):
        logger.debug("settings.json parse failed")
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


def get_effective_provider(default: str = "openai") -> str:
    """获取当前有效 provider。

    优先级：
    1. 环境变量 TERMPILOT_PROVIDER
    2. settings.json 中的 env.TERMPILOT_PROVIDER
    3. settings.json 顶层 provider 字段
    4. 默认值

    未知 provider 默认按 openai_compatible 处理，这样便于对接大多数业内兼容接口。
    """
    settings = get_settings()
    env = get_settings_env()
    provider = _first_nonempty(
        os.environ.get("TERMPILOT_PROVIDER"),
        env.get("TERMPILOT_PROVIDER"),
        settings.get("provider"),
        default,
    )
    normalized = _normalize_provider(provider)
    logger.debug("effective provider: %s (raw=%s)", normalized, provider)
    return normalized


def apply_settings_env() -> None:
    """将 settings.json 中的 env 注入到 os.environ。

    对应 TS utils/managedEnv.ts applySafeConfigEnvironmentVariables()。

    把 settings.json 中的 env 字段写入 os.environ，
    使得后续创建 API 客户端时自动使用。
    这就是"只改 settings.json 就能切换 provider"的核心机制。
    """
    settings_env = get_settings_env()
    if settings_env:
        logger.debug("injecting %d env vars from settings: %s",
                     len(settings_env), ", ".join(settings_env.keys()))
    os.environ.update(settings_env)


def get_effective_api_key(provider: str | None = None) -> str | None:
    """获取有效的 API Key。

    对应 TS utils/auth.ts getAnthropicApiKey() +
    services/api/client.ts configureApiKeyHeaders()。

    TS 中 key 来源优先级：
    1. ANTHROPIC_API_KEY 环境变量
    2. ANTHROPIC_AUTH_TOKEN（Bearer token，TermPilot 用这个）
    3. apiKeyHelper（外部命令获取）
    4. OAuth token

    Python 版按 provider 读取不同变量，并保留常见别名兼容。
    """
    provider = _normalize_provider(provider or get_effective_provider())
    env = get_settings_env()
    if provider == "anthropic":
        candidates = [
            ("env:ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY")),
            ("settings:ANTHROPIC_API_KEY", env.get("ANTHROPIC_API_KEY")),
            ("env:ANTHROPIC_AUTH_TOKEN", os.environ.get("ANTHROPIC_AUTH_TOKEN")),
            ("settings:ANTHROPIC_AUTH_TOKEN", env.get("ANTHROPIC_AUTH_TOKEN")),
        ]
    elif provider == "openai":
        candidates = [
            ("env:OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY")),
            ("settings:OPENAI_API_KEY", env.get("OPENAI_API_KEY")),
            ("env:TERMPILOT_API_KEY", os.environ.get("TERMPILOT_API_KEY")),
            ("settings:TERMPILOT_API_KEY", env.get("TERMPILOT_API_KEY")),
        ]
    else:
        candidates = [
            ("env:TERMPILOT_API_KEY", os.environ.get("TERMPILOT_API_KEY")),
            ("settings:TERMPILOT_API_KEY", env.get("TERMPILOT_API_KEY")),
            ("env:OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY")),
            ("settings:OPENAI_API_KEY", env.get("OPENAI_API_KEY")),
            ("env:ZHIPU_API_KEY", os.environ.get("ZHIPU_API_KEY")),
            ("settings:ZHIPU_API_KEY", env.get("ZHIPU_API_KEY")),
            ("env:DEEPSEEK_API_KEY", os.environ.get("DEEPSEEK_API_KEY")),
            ("settings:DEEPSEEK_API_KEY", env.get("DEEPSEEK_API_KEY")),
            ("env:DASHSCOPE_API_KEY", os.environ.get("DASHSCOPE_API_KEY")),
            ("settings:DASHSCOPE_API_KEY", env.get("DASHSCOPE_API_KEY")),
            ("env:MOONSHOT_API_KEY", os.environ.get("MOONSHOT_API_KEY")),
            ("settings:MOONSHOT_API_KEY", env.get("MOONSHOT_API_KEY")),
            ("env:SILICONFLOW_API_KEY", os.environ.get("SILICONFLOW_API_KEY")),
            ("settings:SILICONFLOW_API_KEY", env.get("SILICONFLOW_API_KEY")),
            ("env:OPENROUTER_API_KEY", os.environ.get("OPENROUTER_API_KEY")),
            ("settings:OPENROUTER_API_KEY", env.get("OPENROUTER_API_KEY")),
            ("env:GROQ_API_KEY", os.environ.get("GROQ_API_KEY")),
            ("settings:GROQ_API_KEY", env.get("GROQ_API_KEY")),
            ("env:TOGETHER_API_KEY", os.environ.get("TOGETHER_API_KEY")),
            ("settings:TOGETHER_API_KEY", env.get("TOGETHER_API_KEY")),
            ("env:FIREWORKS_API_KEY", os.environ.get("FIREWORKS_API_KEY")),
            ("settings:FIREWORKS_API_KEY", env.get("FIREWORKS_API_KEY")),
            ("env:OLLAMA_API_KEY", os.environ.get("OLLAMA_API_KEY")),
            ("settings:OLLAMA_API_KEY", env.get("OLLAMA_API_KEY")),
            ("env:ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY")),
            ("settings:ANTHROPIC_API_KEY", env.get("ANTHROPIC_API_KEY")),
        ]

    source = None
    key = None
    for candidate_source, candidate_value in candidates:
        if candidate_value:
            source = candidate_source
            key = candidate_value
            break

    if key:
        logger.debug("API key found: source=%s, prefix=%s...", source, key[:6])
    else:
        logger.debug("no API key found in any source for provider=%s", provider)
    return key


def get_effective_base_url(provider: str | None = None) -> str | None:
    """获取有效的 API Base URL。

    支持 provider 专属变量、通用变量和 settings.json 顶层字段。
    对 openai_compatible 来说，base URL 通常是必需的。
    """
    provider = _normalize_provider(provider or get_effective_provider())
    settings = get_settings()
    env = get_settings_env()

    if provider == "anthropic":
        return _first_nonempty(
            os.environ.get("ANTHROPIC_BASE_URL"),
            env.get("ANTHROPIC_BASE_URL"),
            settings.get("base_url"),
        )
    if provider == "openai":
        return _first_nonempty(
            os.environ.get("OPENAI_BASE_URL"),
            env.get("OPENAI_BASE_URL"),
            os.environ.get("TERMPILOT_BASE_URL"),
            env.get("TERMPILOT_BASE_URL"),
            settings.get("base_url"),
        )
    return _first_nonempty(
        os.environ.get("TERMPILOT_BASE_URL"),
        env.get("TERMPILOT_BASE_URL"),
        os.environ.get("OPENAI_BASE_URL"),
        env.get("OPENAI_BASE_URL"),
        os.environ.get("ZHIPU_BASE_URL"),
        env.get("ZHIPU_BASE_URL"),
        os.environ.get("DEEPSEEK_BASE_URL"),
        env.get("DEEPSEEK_BASE_URL"),
        os.environ.get("DASHSCOPE_BASE_URL"),
        env.get("DASHSCOPE_BASE_URL"),
        os.environ.get("MOONSHOT_BASE_URL"),
        env.get("MOONSHOT_BASE_URL"),
        os.environ.get("SILICONFLOW_BASE_URL"),
        env.get("SILICONFLOW_BASE_URL"),
        os.environ.get("OPENROUTER_BASE_URL"),
        env.get("OPENROUTER_BASE_URL"),
        os.environ.get("GROQ_BASE_URL"),
        env.get("GROQ_BASE_URL"),
        os.environ.get("TOGETHER_BASE_URL"),
        env.get("TOGETHER_BASE_URL"),
        os.environ.get("FIREWORKS_BASE_URL"),
        env.get("FIREWORKS_BASE_URL"),
        os.environ.get("OLLAMA_BASE_URL"),
        env.get("OLLAMA_BASE_URL"),
        os.environ.get("ANTHROPIC_BASE_URL"),
        env.get("ANTHROPIC_BASE_URL"),
        settings.get("base_url"),
    )


def get_effective_model(default: str = "claude-sonnet-4-20250514", provider: str | None = None) -> str:
    """获取默认模型。

    会按 provider 读取最自然的模型变量，同时保留旧变量名兼容。
    """
    provider = _normalize_provider(provider or get_effective_provider())
    settings = get_settings()
    env = get_settings_env()
    if provider == "anthropic":
        model = _first_nonempty(
            os.environ.get("ANTHROPIC_MODEL"),
            env.get("ANTHROPIC_MODEL"),
            os.environ.get("TERMPILOT_MODEL"),
            env.get("TERMPILOT_MODEL"),
            settings.get("model"),
            default,
        )
    else:
        model = _first_nonempty(
            os.environ.get("OPENAI_MODEL"),
            env.get("OPENAI_MODEL"),
            os.environ.get("TERMPILOT_MODEL"),
            env.get("TERMPILOT_MODEL"),
            os.environ.get("ZHIPU_MODEL"),
            env.get("ZHIPU_MODEL"),
            os.environ.get("DEEPSEEK_MODEL"),
            env.get("DEEPSEEK_MODEL"),
            os.environ.get("DASHSCOPE_MODEL"),
            env.get("DASHSCOPE_MODEL"),
            os.environ.get("MOONSHOT_MODEL"),
            env.get("MOONSHOT_MODEL"),
            os.environ.get("SILICONFLOW_MODEL"),
            env.get("SILICONFLOW_MODEL"),
            os.environ.get("OPENROUTER_MODEL"),
            env.get("OPENROUTER_MODEL"),
            os.environ.get("GROQ_MODEL"),
            env.get("GROQ_MODEL"),
            os.environ.get("TOGETHER_MODEL"),
            env.get("TOGETHER_MODEL"),
            os.environ.get("FIREWORKS_MODEL"),
            env.get("FIREWORKS_MODEL"),
            os.environ.get("OLLAMA_MODEL"),
            env.get("OLLAMA_MODEL"),
            os.environ.get("ANTHROPIC_MODEL"),
            env.get("ANTHROPIC_MODEL"),
            settings.get("model"),
            default,
        )
    logger.debug("effective model: %s (default=%s)", model, default)
    return model


def get_context_window() -> int:
    """获取上下文窗口大小（tokens）。

    用于上下文压缩的阈值计算。
    默认 200000。
    """
    return int(
        os.environ.get("CLAUDE_CONTEXT_WINDOW", "")
        or get_settings_env().get("CLAUDE_CONTEXT_WINDOW", "")
        or "200000"
    )
