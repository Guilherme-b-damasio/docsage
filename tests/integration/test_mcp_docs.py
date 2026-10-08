"""Keeps docs/mcp.md in step with what the server actually exposes."""

import asyncio
import re
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from docsage.container import Container, Settings  # noqa: E402
from docsage.interfaces.mcp_server import build_server  # noqa: E402

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "mcp.md"


def table_rows(heading):
    """First-column names and second-column arguments of the table under ``### heading``."""
    section = GUIDE.read_text(encoding="utf-8").split(f"### {heading}\n", 1)[1]
    section = section.split("\n#", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        name = re.fullmatch(r"`([^`]+)`", cells[0])
        if name:
            rows[name.group(1)] = re.findall(r"`([^`]+)`", cells[1]) if len(cells) > 2 else []
    return rows


def capabilities(tmp_path):
    async def run():
        server = build_server(Container(Settings(index_path=tmp_path / "index.json")))
        async with Client(server) as client:
            return (
                (await client.list_tools()).tools,
                (await client.list_resources()).resources,
                (await client.list_resource_templates()).resource_templates,
                (await client.list_prompts()).prompts,
            )

    return asyncio.run(run())


def test_guide_documents_every_tool_and_its_arguments(tmp_path):
    tools, _, _, _ = capabilities(tmp_path)

    documented = table_rows("Tools")

    assert documented == {
        tool.name: list(tool.input_schema.get("properties", {})) for tool in tools
    }


def test_guide_documents_every_resource(tmp_path):
    _, resources, templates, _ = capabilities(tmp_path)

    served = {str(item.uri) for item in resources} | {item.uri_template for item in templates}

    assert set(table_rows("Resources")) == served


def test_guide_documents_every_prompt_and_its_arguments(tmp_path):
    _, _, _, prompts = capabilities(tmp_path)

    documented = table_rows("Prompts")

    assert documented == {
        prompt.name: [argument.name for argument in prompt.arguments] for prompt in prompts
    }
