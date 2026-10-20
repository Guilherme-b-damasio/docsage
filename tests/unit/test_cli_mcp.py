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

    def fake_build(services, **options):
        built_with.append((services, options))
        return server

    monkeypatch.setattr(mcp_server, "build_server", fake_build)

    assert cli.main(["--index", str(tmp_path / "index.json"), "mcp"]) == 0
    assert server.transports == ["stdio"]
    services, options = built_with[0]
    assert isinstance(services, Container)
    assert options == {"watch": [], "interval": 1.0}


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
    monkeypatch.setattr(mcp_server, "build_server", lambda services, **options: server)

    argv = ["--index", str(tmp_path / "index.json"), "mcp", "--http", "--port", "9000"]
    assert cli.main(argv) == 0
    assert server.transports == ["streamable-http"]
    assert server.options == [{"host": "127.0.0.1", "port": 9000, "streamable_http_path": "/mcp"}]
    assert "http://127.0.0.1:9000/mcp" in capsys.readouterr().err


def test_mcp_command_defaults_to_port_8765(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    import docsage.interfaces.mcp_server as mcp_server

    server = FakeServer()
    monkeypatch.setattr(mcp_server, "build_server", lambda services, **options: server)

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


def test_serve_command_runs_the_http_api_with_uvicorn(tmp_path, monkeypatch, capsys):
    pytest.importorskip("fastapi")
    import uvicorn
    from fastapi import FastAPI

    runs = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **options: runs.append((app, options)))

    index = str(tmp_path / "index.json")
    assert cli.main(["--index", index, "serve", "--host", "0.0.0.0", "--port", "9000"]) == 0

    app, options = runs[0]
    assert isinstance(app, FastAPI)
    assert options == {"host": "0.0.0.0", "port": 9000}
    assert "http://0.0.0.0:9000" in capsys.readouterr().err


def test_serve_command_explains_how_to_install_the_extra(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "docsage.interfaces.http_api", None)

    assert cli.main(["--index", str(tmp_path / "index.json"), "serve"]) == 2
    assert 'pip install "docsage[api]"' in capsys.readouterr().err


def test_mcp_command_watches_folders_while_serving(tmp_path, monkeypatch, capsys):
    pytest.importorskip("mcp")
    import docsage.interfaces.mcp_server as mcp_server

    docs, notes = tmp_path / "docs", tmp_path / "notes"
    docs.mkdir()
    notes.mkdir()
    server = FakeServer()
    built_with = []

    def fake_build(services, **options):
        built_with.append(options)
        return server

    monkeypatch.setattr(mcp_server, "build_server", fake_build)
    argv = ["--index", str(tmp_path / "index.json"), "mcp"]
    argv += ["--watch", str(docs), "--watch", str(notes), "--interval", "0.5"]

    assert cli.main(argv) == 0
    assert built_with == [{"watch": [docs, notes], "interval": 0.5}]
    assert server.transports == ["stdio"]
    assert f"keeping the index in sync with {docs}, {notes}" in capsys.readouterr().err


def test_mcp_command_refuses_to_watch_a_missing_folder(tmp_path, monkeypatch, capsys):
    pytest.importorskip("mcp")
    import docsage.interfaces.mcp_server as mcp_server

    monkeypatch.setattr(mcp_server, "build_server", lambda services, **options: FakeServer())
    missing = tmp_path / "nowhere"
    argv = ["--index", str(tmp_path / "index.json"), "mcp", "--watch", str(missing)]

    assert cli.main(argv) == 2
    assert f"cannot watch missing paths: {missing}" in capsys.readouterr().err
