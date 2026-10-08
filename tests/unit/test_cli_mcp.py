import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

import docsage.interfaces.cli as cli
from docsage.container import Container


class FakeServer:
    def __init__(self):
        self.transports = []
        self.options = []

    def run(self, transport, **options):
        self.transports.append(transport)
        self.options.append(options)


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


def test_mcp_command_runs_the_server_over_http(tmp_path, monkeypatch, capsys):
    pytest.importorskip("mcp")
    import docsage.interfaces.mcp_server as mcp_server

    server = FakeServer()
    monkeypatch.setattr(mcp_server, "build_server", lambda services: server)

    argv = ["--index", str(tmp_path / "index.json"), "mcp", "--http", "--port", "9000"]
    assert cli.main(argv) == 0
    assert server.transports == ["streamable-http"]
    assert server.options == [{"host": "127.0.0.1", "port": 9000, "streamable_http_path": "/mcp"}]
    assert "http://127.0.0.1:9000/mcp" in capsys.readouterr().err


def test_mcp_command_defaults_to_port_8765(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    import docsage.interfaces.mcp_server as mcp_server

    server = FakeServer()
    monkeypatch.setattr(mcp_server, "build_server", lambda services: server)

    assert cli.main(["--index", str(tmp_path / "index.json"), "mcp", "--http"]) == 0
    assert server.options[0]["port"] == 8765


@pytest.mark.parametrize("port", ["0", "70000", "http"])
def test_mcp_command_rejects_invalid_ports(tmp_path, port, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--index", str(tmp_path / "index.json"), "mcp", "--http", "--port", port])

    assert exit_info.value.code == 2
    assert "--port" in capsys.readouterr().err


def test_mcp_command_serves_a_real_client_over_http(tmp_path):
    pytest.importorskip("mcp")
    from mcp import Client

    (tmp_path / "notes.md").write_text("Lisbon is the capital of Portugal.", encoding="utf-8")
    index = tmp_path / "index.json"
    assert cli.main(["--index", str(index), "index", str(tmp_path / "notes.md")]) == 0
    port = _free_port()
    src = Path(cli.__file__).resolve().parents[2]
    command = [sys.executable, "-m", "docsage.interfaces.cli", "--index", str(index)]
    process = subprocess.Popen(
        [*command, "mcp", "--http", "--port", str(port)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(src)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port, process)

        async def run():
            async with Client(f"http://127.0.0.1:{port}/mcp", read_timeout_seconds=30) as client:
                return await client.call_tool("search_documents", {"query": "Portugal"})

        result = asyncio.run(run())
    finally:
        process.terminate()
        process.wait(timeout=10)

    assert not result.is_error
    assert "Lisbon is the capital of Portugal." in result.content[0].text


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_for_port(port, process, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"docsage mcp --http exited with {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    pytest.fail(f"docsage mcp --http did not listen on port {port} within {timeout}s")
