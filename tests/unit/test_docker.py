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
