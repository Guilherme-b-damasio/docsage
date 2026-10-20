"""``build_server(watch=...)``: the index follows a folder while the server runs, and
listening clients hear that ``docsage://documents`` changed. Uses the real polling
watcher on a temporary folder."""

import asyncio
import json

import pytest

pytest.importorskip("mcp")

import anyio  # noqa: E402
from mcp import Client  # noqa: E402
from mcp.shared.subscriptions import ResourcesListChanged, ResourceUpdated  # noqa: E402

from docsage.container import Container, Settings  # noqa: E402
from docsage.interfaces.mcp_server import DOCUMENTS_URI, build_server  # noqa: E402

INTERVAL = 0.05
TIMEOUT = 10


def sources_in(result):
    return {item["source"] for item in json.loads(result.contents[0].text)["documents"]}


async def next_documents_change(subscription):
    """Waits for the ``docsage://documents`` update that follows each list change."""
    with anyio.fail_after(TIMEOUT):
        async for event in subscription:
            if event == ResourceUpdated(uri=DOCUMENTS_URI):
                return event


def test_watched_files_are_indexed_and_listeners_are_notified(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    note = docs / "note.md"
    container = Container(Settings(index_path=tmp_path / ".docsage" / "index.json"))
    server = build_server(container, watch=[docs], interval=INTERVAL)

    async def session():
        async with Client(server) as client:
            async with client.listen(
                resources_list_changed=True, resource_subscriptions=[DOCUMENTS_URI]
            ) as subscription:
                note.write_text("# Note\n\nWatching keeps the index fresh.", encoding="utf-8")
                await next_documents_change(subscription)
                after_write = sources_in(await client.read_resource(DOCUMENTS_URI))

                note.unlink()
                await next_documents_change(subscription)
                after_delete = sources_in(await client.read_resource(DOCUMENTS_URI))
        return after_write, after_delete

    after_write, after_delete = asyncio.run(session())

    assert after_write == {str(note)}
    assert after_delete == set()


def test_list_changed_comes_before_the_documents_update(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    container = Container(Settings(index_path=tmp_path / ".docsage" / "index.json"))
    server = build_server(container, watch=[docs], interval=INTERVAL)

    async def session():
        events = []
        async with Client(server) as client:
            async with client.listen(
                resources_list_changed=True, resource_subscriptions=[DOCUMENTS_URI]
            ) as subscription:
                (docs / "a.md").write_text("alpha", encoding="utf-8")
                with anyio.fail_after(TIMEOUT):
                    async for event in subscription:
                        events.append(event)
                        if len(events) == 2:
                            break
        return events

    assert asyncio.run(session()) == [ResourcesListChanged(), ResourceUpdated(uri=DOCUMENTS_URI)]


def test_tools_keep_working_and_their_writes_survive_the_watcher(tmp_path):
    docs, extra = tmp_path / "docs", tmp_path / "extra"
    docs.mkdir()
    extra.mkdir()
    (extra / "manual.md").write_text("indexed by a tool call", encoding="utf-8")
    container = Container(Settings(index_path=tmp_path / ".docsage" / "index.json"))
    server = build_server(container, watch=[docs], interval=INTERVAL)

    async def session():
        async with Client(server) as client:
            async with client.listen(
                resources_list_changed=True, resource_subscriptions=[DOCUMENTS_URI]
            ) as subscription:
                await client.call_tool("index_path", {"path": str(extra)})
                (docs / "watched.md").write_text("indexed by the watcher", encoding="utf-8")
                await next_documents_change(subscription)
                return sources_in(await client.read_resource(DOCUMENTS_URI))

    assert asyncio.run(session()) == {str(extra / "manual.md"), str(docs / "watched.md")}


def test_without_watch_folders_nothing_is_watched(tmp_path):
    class NoWatching:
        def live_watch_service(self, *args, **kwargs):
            raise AssertionError("must not watch")

    async def session():
        async with Client(build_server(NoWatching())) as client:
            return await client.list_tools()

    assert asyncio.run(session()).tools
