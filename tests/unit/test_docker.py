"""The Docker files are not built in CI, so check they agree with the CLI and the package."""

import json
import re
import tomllib
from pathlib import Path

import pytest

from docsage.interfaces.cli import DEFAULT_API_PORT, DEFAULT_HTTP_PORT, _parser

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"


def _instruction(name: str) -> str:
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    (value,) = [line.split(" ", 1)[1] for line in lines if line.startswith(f"{name} ")]
    return value


def _extras() -> set[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(pyproject["project"]["optional-dependencies"])


def test_dockerfile_installs_extras_the_package_defines():
    extras = _instruction("ARG").removeprefix("EXTRAS=").split(",")

    assert set(extras) <= _extras()
    assert {"api", "mcp"} <= set(extras)


def test_dockerfile_default_command_is_a_valid_serve_invocation():
    assert json.loads(_instruction("ENTRYPOINT")) == ["docsage"]

    args = _parser().parse_args(json.loads(_instruction("CMD")))

    assert args.handler.__name__ == "_serve"
    assert (args.host, args.port) == ("0.0.0.0", DEFAULT_API_PORT)


def test_dockerfile_exposes_the_api_and_mcp_ports():
    ports = {int(port) for port in _instruction("EXPOSE").split()}

    assert ports == {DEFAULT_API_PORT, DEFAULT_HTTP_PORT}


def test_dockerfile_runs_as_an_unprivileged_user():
    assert _instruction("USER") != "root"


@pytest.mark.parametrize("path", ["src", "pyproject.toml", "README.md", "LICENSE"])
def test_docker_context_keeps_what_the_build_copies(path):
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()

    assert (ROOT / path).exists()
    assert not any(re.fullmatch(pattern.replace("*", ".*"), path) for pattern in ignored)


def _compose_commands() -> dict[str, list[str]]:
    """Each service's ``command:``, written as a JSON array in docker-compose.yml."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    services = re.findall(r"^  (\w+):\n((?:    .*\n|\n)+)", compose, re.MULTILINE)
    return {
        name: json.loads(command)
        for name, body in services
        for command in re.findall(r"^    command: (\[.*\])$", body, re.MULTILINE)
    }


def test_compose_services_run_valid_commands_on_the_ports_they_publish():
    commands = _compose_commands()

    assert set(commands) == {"api", "mcp"}
    api = _parser().parse_args(commands["api"])
    mcp = _parser().parse_args(commands["mcp"])
    assert (api.handler.__name__, api.host, api.port) == ("_serve", "0.0.0.0", DEFAULT_API_PORT)
    assert (mcp.handler.__name__, mcp.http, mcp.host) == ("_mcp", True, "0.0.0.0")
    assert mcp.port == DEFAULT_HTTP_PORT

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert f'"{api.port}:{api.port}"' in compose
    assert f'"{mcp.port}:{mcp.port}"' in compose
