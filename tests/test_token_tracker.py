"""Token 追踪和费用计算测试。"""

from __future__ import annotations

import pytest

from termpilot.token_tracker import (
    TokenUsage,
    CostTracker,
    _get_model_family,
    _format_tokens,
    usage_from_anthropic,
    usage_from_openai,
)


class TestTokenUsage:
    def test_default(self) -> None:
        u = TokenUsage()
        assert u.input_tokens == 0
        assert u.total_tokens == 0

    def test_total_tokens(self) -> None:
        u = TokenUsage(input_tokens=100, output_tokens=50,
                       cache_creation_input_tokens=20, cache_read_input_tokens=30)
        assert u.total_tokens == 200

    def test_add(self) -> None:
        a = TokenUsage(input_tokens=100, output_tokens=50)
        b = TokenUsage(input_tokens=200, output_tokens=30)
        c = a + b
        assert c.input_tokens == 300
        assert c.output_tokens == 80


class TestModelFamily:
    def test_sonnet(self) -> None:
        assert _get_model_family("claude-sonnet-4-20250514") == "claude-sonnet-4"

    def test_opus(self) -> None:
        assert _get_model_family("claude-opus-4-6") == "claude-opus-4"

    def test_haiku(self) -> None:
        assert _get_model_family("claude-haiku-4-5-20251001") == "claude-haiku-4"

    def test_unknown(self) -> None:
        assert _get_model_family("glm-4-flash") == ""


class TestFormatTokens:
    def test_small(self) -> None:
        assert _format_tokens(42) == "42"

    def test_thousands(self) -> None:
        assert _format_tokens(1500) == "1.5k"

    def test_millions(self) -> None:
        assert _format_tokens(2_500_000) == "2.5M"


class TestCostTracker:
    def test_empty(self) -> None:
        tracker = CostTracker()
        assert tracker.get_total_cost() == 0.0
        assert tracker.total_usage.total_tokens == 0

    def test_single_usage(self) -> None:
        tracker = CostTracker()
        usage = TokenUsage(input_tokens=100_000, output_tokens=1_000)
        tracker.add_usage("claude-sonnet-4-20250514", usage)
        cost = tracker.get_total_cost()
        # 100k * $3/M + 1k * $15/M = $0.3 + $0.015 = $0.315
        assert abs(cost - 0.315) < 0.001

    def test_multiple_models(self) -> None:
        tracker = CostTracker()
        tracker.add_usage("claude-sonnet-4", TokenUsage(input_tokens=100_000, output_tokens=1_000))
        tracker.add_usage("claude-haiku-4", TokenUsage(input_tokens=50_000, output_tokens=500))
        cost = tracker.get_total_cost()
        # sonnet: 100k * $3/M + 1k * $15/M = $0.315
        # haiku:  50k * $1/M + 500 * $5/M = $0.0525
        assert abs(cost - 0.3675) < 0.001

    def test_unknown_model_zero_cost(self) -> None:
        tracker = CostTracker()
        tracker.add_usage("glm-4-flash", TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000))
        assert tracker.get_total_cost() == 0.0

    def test_cache_tokens(self) -> None:
        tracker = CostTracker()
        usage = TokenUsage(
            input_tokens=50_000,
            cache_creation_input_tokens=10_000,
            cache_read_input_tokens=40_000,
            output_tokens=1_000,
        )
        tracker.add_usage("claude-sonnet-4", usage)
        cost = tracker.get_total_cost()
        # input: 50k * $3/M = $0.15
        # cache_write: 10k * $3.75/M = $0.0375
        # cache_read: 40k * $0.30/M = $0.012
        # output: 1k * $15/M = $0.015
        expected = 0.15 + 0.0375 + 0.012 + 0.015
        assert abs(cost - expected) < 0.001

    def test_format_per_response(self) -> None:
        tracker = CostTracker()
        usage = TokenUsage(input_tokens=1_000, output_tokens=500)
        result = tracker.format_per_response("claude-sonnet-4", usage)
        assert "cost:" in result
        assert "tokens:" in result
        assert "in" in result
        assert "out" in result

    def test_format_report_empty(self) -> None:
        tracker = CostTracker()
        assert "No API usage" in tracker.format_report()

    def test_format_report_with_data(self) -> None:
        tracker = CostTracker()
        tracker.add_usage("claude-sonnet-4", TokenUsage(input_tokens=1_000, output_tokens=100))
        report = tracker.format_report()
        assert "Total cost:" in report


class TestUsageFromApi:
    def test_anthropic_usage(self) -> None:
        class MockUsage:
            input_tokens = 100
            output_tokens = 50
            cache_creation_input_tokens = 10
            cache_read_input_tokens = 20
        result = usage_from_anthropic(MockUsage())
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.cache_creation_input_tokens == 10
        assert result.cache_read_input_tokens == 20

    def test_anthropic_missing_fields(self) -> None:
        class MockUsage:
            input_tokens = 100
            output_tokens = 50
        result = usage_from_anthropic(MockUsage())
        assert result.cache_creation_input_tokens == 0

    def test_openai_usage(self) -> None:
        class MockUsage:
            prompt_tokens = 200
            completion_tokens = 80
        result = usage_from_openai(MockUsage())
        assert result.input_tokens == 200
        assert result.output_tokens == 80
        assert result.cache_creation_input_tokens == 0
