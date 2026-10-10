"""Command-line interface. Thin layer: parse args, call a use case, print."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from docsage import __version__
from docsage.container import DASHBOARD_FORMATS, Container, load_settings
from docsage.infrastructure.config import CONFIG_FILENAME, ConfigError
from docsage.infrastructure.logs import configure_logging
from docsage.infrastructure.units import human_size
from docsage.interfaces.paths import expand_paths
from docsage.interfaces.serializers import (
    answer_to_dict,
    dumps,
    search_results_to_dict,
    stats_to_dict,
)

Handler = Callable[[Container, argparse.Namespace], int]

DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8765
HTTP_PATH = "/mcp"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    configure_logging(verbose=args.verbose)
    try:
        settings = load_settings(
            _config_path(args.config), index_path=args.index, model=getattr(args, "model", None)
        )
    except ConfigError as error:
        print(f"docsage: {error}", file=sys.stderr)
        return 2
    handler: Handler = args.handler
    return handler(Container(settings), args)


def _config_path(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    default = Path(CONFIG_FILENAME)
    return default if default.is_file() else None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docsage", description="Ask questions about your documents."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--index", type=Path, default=None, help="index file (default: .docsage/index.json)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"settings file (default: ./{CONFIG_FILENAME} if present)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log debug events (key=value) to stderr"
    )
    commands = parser.add_subparsers(required=True)

    index = commands.add_parser("index", help="index files or folders")
    index.add_argument("paths", nargs="+", type=Path)
    index.add_argument(
        "--force", action="store_true", help="re-index files even if they have not changed"
    )
    index.set_defaults(handler=_index)

    remove = commands.add_parser("remove", help="drop a file or folder from the index")
    remove.add_argument("path", type=Path)
    remove.set_defaults(handler=_remove)

    search = commands.add_parser("search", help="show the best matching chunks")
    search.add_argument("query")
    search.add_argument("-k", "--top-k", type=int, default=5)
    search.add_argument("--json", action="store_true", help="print results as JSON")
    search.set_defaults(handler=_search)

    stats = commands.add_parser("stats", help="summarize the index")
    stats.add_argument("--top", type=int, default=10, help="how many top terms to show")
    stats.add_argument("--json", action="store_true", help="print stats as JSON")
    stats.set_defaults(handler=_stats)

    dashboard = commands.add_parser("dashboard", help="write an HTML dashboard of the index")
    dashboard.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="file to write (default: print to stdout)",
    )
    dashboard.add_argument(
        "--format", choices=sorted(DASHBOARD_FORMATS), default="html", help="default: html"
    )
    dashboard.add_argument("--top", type=int, default=15, help="how many top terms to chart")
    dashboard.set_defaults(handler=_dashboard)

    ask = commands.add_parser("ask", help="answer a question with Claude")
    ask.add_argument("question")
    ask.add_argument("-k", "--top-k", type=int, default=5)
    ask.add_argument("--model", default=None)
    ask.add_argument("--json", action="store_true", help="print the answer as JSON")
    ask.set_defaults(handler=_ask)

    mcp = commands.add_parser("mcp", help="serve the index to MCP clients (stdio or HTTP)")
    mcp.add_argument(
        "--http", action="store_true", help="serve over Streamable HTTP instead of stdio"
    )
    mcp.add_argument(
        "--host",
        default=DEFAULT_HTTP_HOST,
        help=f"HTTP bind address (default: {DEFAULT_HTTP_HOST})",
    )
    mcp.add_argument(
        "--port",
        type=_port,
        default=DEFAULT_HTTP_PORT,
        help=f"HTTP port (default: {DEFAULT_HTTP_PORT})",
    )
    mcp.set_defaults(handler=_mcp)
    return parser


def _index(container: Container, args: argparse.Namespace) -> int:
    report = container.indexing_service().index(expand_paths(args.paths), force=args.force)
    print(f"Indexed {report.documents} documents into {report.chunks} chunks.")
    if report.unchanged:
        print(f"Skipped {report.unchanged} unchanged documents (use --force to re-index).")
    for path in report.skipped:
        print(f"  skipped (unsupported): {path}", file=sys.stderr)
    return 0


def _remove(container: Container, args: argparse.Namespace) -> int:
    report = container.removal_service().remove(args.path)
    if not report.documents:
        print(f"Nothing indexed under {args.path}.", file=sys.stderr)
        return 1
    print(f"Removed {len(report.documents)} documents ({report.chunks} chunks).")
    return 0


def _search(container: Container, args: argparse.Namespace) -> int:
    results = container.search_service().search(args.query, args.top_k)
    if args.json:
        print(dumps(search_results_to_dict(args.query, results)))
        return 0 if results else 1
    if not results:
        print("No matches.")
        return 1
    for rank, result in enumerate(results, start=1):
        preview = result.chunk.text[:160].replace("\n", " ")
        matched = f" (matched: {', '.join(result.matched_terms)})" if result.matched_terms else ""
        print(f"{rank}. [{result.score:.2f}] {result.chunk.citation}{matched}\n   {preview}...")
    return 0


def _stats(container: Container, args: argparse.Namespace) -> int:
    stats = container.stats_service().stats(args.top)
    if args.json:
        print(dumps(stats_to_dict(stats)))
        return 0
    print(f"Documents:  {stats.documents}")
    print(f"Chunks:     {stats.chunks}")
    print(f"Terms:      {stats.terms} ({stats.vocabulary} distinct)")
    print(f"Index size: {human_size(stats.index_bytes)}")
    if stats.top_terms:
        print("Top terms:")
        width = max(len(term) for term, _ in stats.top_terms)
        for term, count in stats.top_terms:
            print(f"  {term:<{width}}  {count}")
    return 0


def _dashboard(container: Container, args: argparse.Namespace) -> int:
    content = container.dashboard_service(args.format).render(top=args.top)
    if args.output is None:
        _write_stdout(content)
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


def _write_stdout(content: str) -> None:
    """Writes ``content`` even when stdout's encoding (e.g. cp1252 when redirected on
    Windows) cannot represent it, by sending UTF-8 bytes instead."""
    try:
        sys.stdout.write(content)
    except UnicodeEncodeError:
        sys.stdout.flush()
        sys.stdout.buffer.write(content.encode("utf-8"))
        sys.stdout.buffer.flush()


def _ask(container: Container, args: argparse.Namespace) -> int:
    answer = container.question_answering_service().ask(args.question, args.top_k)
    if args.json:
        print(dumps(answer_to_dict(answer)))
        return 0
    print(answer.text)
    if answer.sources:
        print("\nSources:")
        for index, result in enumerate(answer.sources, start=1):
            print(f"  [{index}] {result.chunk.citation}")
    return 0


def _mcp(container: Container, args: argparse.Namespace) -> int:
    try:
        from docsage.interfaces.mcp_server import build_server
    except ImportError:
        print('docsage: the MCP server needs: pip install "docsage[mcp]"', file=sys.stderr)
        return 2
    server = build_server(container)
    if args.http:
        url = f"http://{args.host}:{args.port}{HTTP_PATH}"
        print(f"docsage: serving MCP over Streamable HTTP at {url}", file=sys.stderr)
        server.run(
            "streamable-http", host=args.host, port=args.port, streamable_http_path=HTTP_PATH
        )
        return 0
    # stdout carries the protocol; logs already go to stderr.
    server.run("stdio")
    return 0


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port must be between 1 and 65535, got {port}")
    return port


if __name__ == "__main__":
    raise SystemExit(main())
