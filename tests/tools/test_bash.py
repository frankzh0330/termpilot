"""bash 工具测试。"""

import pytest

from termpilot.sandbox import SandboxManager
from termpilot.sandbox.base import SandboxAdapter
from termpilot.tools.bash import BashTool, classify_command


class FakeAdapter(SandboxAdapter):
    name = "fake"

    def is_available(self) -> bool:
        return True

    def wrap_command(self, command, config, cwd):
        return "printf sandbox-ok"


@pytest.fixture
def tool():
    return BashTool()


class TestBashTool:
    def test_classify_command(self):
        assert classify_command("cat file.txt") == "read"
        assert classify_command("rg hello") == "search"
        assert classify_command("mkdir out") == "write"
        assert classify_command("curl https://example.com") == "network"
        assert classify_command("custom-tool") == "unknown"

    @pytest.mark.asyncio
    async def test_simple(self, tool):
        result = await tool.call(command="echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_with_output(self, tool):
        result = await tool.call(command="echo 'test output'")
        assert "test output" in result

    @pytest.mark.asyncio
    async def test_with_error(self, tool):
        result = await tool.call(command="echo error >&2")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_exit_code(self, tool):
        result = await tool.call(command="exit 1")
        assert "exit code" in result.lower() or "1" in result

    @pytest.mark.asyncio
    async def test_timeout(self, tool):
        result = await tool.call(command="sleep 10", timeout=100)
        assert "超时" in result or "timeout" in result.lower() or "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_cwd_tracking(self, tool, tmp_path):
        old_cwd = BashTool._cwd
        try:
            result = await tool.call(command=f"cd {tmp_path}")
            assert "exit code" in result.lower()

            result = await tool.call(command="pwd")
            assert str(tmp_path) in result
        finally:
            BashTool._cwd = old_cwd

    @pytest.mark.asyncio
    async def test_sandbox_wraps_command(self, tool, tmp_settings, env_clean, monkeypatch):
        tmp_settings({"sandbox": {"enabled": True}})
        monkeypatch.setattr(SandboxManager, "_adapter", FakeAdapter())

        result = await tool.call(command="echo original")

        assert "[sandboxed]" in result
        assert "sandbox-ok" in result

    def test_is_unsafe(self, tool):
        assert tool.is_concurrency_safe is False

    def test_name(self, tool):
        assert tool.name == "bash"
