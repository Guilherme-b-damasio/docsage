import asyncio
import sys
from pathlib import Path

import pytest

import docsage.interfaces.cli as cli
from docsage.container import Container


class FakeServer:
    def __init__(self):
        self.transports = []

    def run(self, transport):
        self.transports.append(transport)


def test_mcp_command_runs_the_server_over_stdio(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    import docsage.interfaces.mcp_server as mcp_server

    server = FakeServer()
    built_with = []

    def fake_build(services):
        built_with.append(services)
        return server

    monkeypatch.setattr(mcp_server, "build_server", fake_build)

    assert cli.main(["--index", str(tmp_path / "index.json"), "mcp"]) == 0
    assert server.transports == ["stdio"]
    assert isinstance(built_with[0], Container)


def test_mcp_command_explains_how_to_install_the_extra(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "docsage.interfaces.mcp_server", None)

    assert cli.main(["--index", str(tmp_path / "index.json"), "mcp"]) == 2
    assert 'pip install "docsage[mcp]"' in capsys.readouterr().err


def test_mcp_command_serves_a_real_client_over_stdio(tmp_path):
    pytest.importorskip("mcp")
    from mcp import Client, StdioServerParameters

    (tmp_path / "notes.md").write_text("Lisbon is the capital of Portugal.", encoding="utf-8")
    index = tmp_path / "index.json"
    assert cli.main(["--index", str(index), "index", str(tmp_path / "notes.md")]) == 0
    src = Path(cli.__file__).resolve().parents[2]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "docsage.interfaces.cli", "--index", str(index), "mcp"],
        env={"PYTHONPATH": str(src)},
        cwd=str(tmp_path),
    )

    async def run():
        async with Client(parameters, read_timeout_seconds=30) as client:
            return await client.call_tool("search_documents", {"query": "Portugal"})

    result = asyncio.run(run())

    assert not result.is_error
    assert "Lisbon is the capital of Portugal." in result.content[0].text
