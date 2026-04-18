"""Token 精确计数 + 费用追踪。

对应 TS: utils/tokens.ts + utils/cost-tracker.ts
从 API 响应中提取真实 token 用量，按模型定价计算费用。

Anthropic API 返回的 usage 字段：
  input_tokens: int
  output_tokens: int
  cache_creation_input_tokens: int (可选)
  cache_read_input_tokens: int (可选)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定价表（$/Mtok）— 对应 TS cost-tracker.ts
# 格式: (input, output, cache_write, cache_read)
# ---------------------------------------------------------------------------
MODEL_PRICING: dict[str, tuple[float, float, float, float]] = {
    # Opus 4.x
    "claude-opus-4": (15.0, 75.0, 18.75, 1.875),
    # Sonnet 4.x
    "claude-sonnet-4": (3.0, 15.0, 3.75, 0.30),
    # Haiku 4.x
    "claude-haiku-4": (1.0, 5.0, 1.25, 0.10),
}

MILLION = 1_000_000


def _get_model_family(model: str) -> str:
    """从模型名提取家族前缀（用于定价表匹配）。

    "claude-sonnet-4-20250514" → "claude-sonnet-4"
    "glm-4-flash" → "" (无匹配定价)
    """
    model_lower = model.lower()
    for prefix in MODEL_PRICING:
        if model_lower.startswith(prefix):
            return prefix
    return ""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    """一次或累计的 token 用量。"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """总 token 数（含缓存）。"""
        return (
                self.input_tokens
                + self.output_tokens
                + self.cache_creation_input_tokens
                + self.cache_read_input_tokens
        )

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens + other.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
        )


class CostTracker:
    """累计追踪 token 用量和费用。

    对应 TS: utils/cost-tracker.ts CostTracker
    """

    def __init__(self) -> None:
        self._by_model: dict[str, TokenUsage] = {}

    def add_usage(self, model: str, usage: TokenUsage) -> None:
        """记录一次 API 调用的 token 用量。"""
        if model not in self._by_model:
            self._by_model[model] = TokenUsage()
        self._by_model[model] = self._by_model[model] + usage
        logger.debug(
            "usage added: model=%s, in=%d, out=%d, cache_write=%d, cache_read=%d",
            model, usage.input_tokens, usage.output_tokens,
            usage.cache_creation_input_tokens, usage.cache_read_input_tokens,
        )

    @property
    def total_usage(self) -> TokenUsage:
        """所有模型的累计用量。"""
        result = TokenUsage()
        for usage in self._by_model.values():
            result = result + usage
        return result

    @staticmethod
    def calculate_cost(usage: TokenUsage, model: str) -> float:
        """计算一次用量对应的 USD 费用。"""
        family = _get_model_family(model)
        if not family:
            return 0.0

        input_rate, output_rate, cache_write_rate, cache_read_rate = MODEL_PRICING[family]
        cost = (
                usage.input_tokens / MILLION * input_rate
                + usage.output_tokens / MILLION * output_rate
                + usage.cache_creation_input_tokens / MILLION * cache_write_rate
                + usage.cache_read_input_tokens / MILLION * cache_read_rate
        )
        return cost

    def get_total_cost(self) -> float:
        """所有模型的累计费用。"""
        total = 0.0
        for model, usage in self._by_model.items():
            total += self.calculate_cost(usage, model)
        return total

    def format_per_response(self, model: str, usage: TokenUsage) -> str:
        """格式化单次回复的费用摘要。"""
        cost = self.calculate_cost(usage, model)
        cost_str = f"${cost:.4f}" if cost < 0.01 else f"${cost:.3f}"
        in_tok = _format_tokens(usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens)
        out_tok = _format_tokens(usage.output_tokens)
        return f"cost: {cost_str} | tokens: {in_tok} in / {out_tok} out"

    def format_report(self) -> str:
        """格式化完整费用报告。"""
        if not self._by_model:
            return "No API usage recorded."

        lines = [f"Total cost: ${self.get_total_cost():.4f}"]
        total = self.total_usage

        if len(self._by_model) > 1:
            lines.append("")
            for model, usage in sorted(self._by_model.items()):
                model_cost = self.calculate_cost(usage, model)
                lines.append(
                    f"  {model}: "
                    f"{_format_tokens(usage.input_tokens)} in, "
                    f"{_format_tokens(usage.output_tokens)} out"
                    f" (${model_cost:.4f})"
                )

        lines.append(
            f"  Total: {_format_tokens(total.input_tokens)} in, "
            f"{_format_tokens(total.output_tokens)} out, "
            f"{_format_tokens(total.cache_creation_input_tokens)} cache_write, "
            f"{_format_tokens(total.cache_read_input_tokens)} cache_read"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _format_tokens(n: int) -> str:
    """格式化 token 数为可读字符串。"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def usage_from_anthropic(usage_obj: Any) -> TokenUsage:
    """从 Anthropic SDK 的 usage 对象提取 TokenUsage。"""
    return TokenUsage(
        input_tokens=getattr(usage_obj, "input_tokens", 0) or 0,
        output_tokens=getattr(usage_obj, "output_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage_obj, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage_obj, "cache_read_input_tokens", 0) or 0,
    )


def usage_from_openai(usage_obj: Any) -> TokenUsage:
    """从 OpenAI SDK 的 usage 对象提取 TokenUsage。"""
    return TokenUsage(
        input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
    )
