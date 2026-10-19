"""Command-line interface. Thin layer: parse args, call a use case, print."""

from __future__ import annotations

import argparse
import sys
import tempfile
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path

from docsage import __version__
from docsage.application.services import WatchUpdate
from docsage.container import (
    CHUNKERS,
    DASHBOARD_FORMATS,
    EVALUATION_FORMATS,
    REPORT_FORMATS,
    RETRIEVERS,
    Container,
    load_settings,
)
from docsage.domain.models import ANSWER_LENGTHS, Answer, SearchResult, is_url
from docsage.infrastructure.config import CONFIG_FILENAME, ConfigError
from docsage.infrastructure.evaluation_set import EvaluationSetError, read_evaluation_set
from docsage.infrastructure.logs import configure_logging
from docsage.infrastructure.text_report import breakdown
from docsage.infrastructure.units import human_size, usage_summary
from docsage.interfaces.paths import expand_paths
from docsage.interfaces.serializers import (
    answer_to_dict,
    dumps,
    evaluation_to_dict,
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
            _config_path(args.config),
            index_path=args.index,
            model=getattr(args, "model", None),
            chunker=getattr(args, "chunker", None),
            retriever=args.retriever,
            rerank=args.rerank,
            answer_language=getattr(args, "language", None),
            answer_length=getattr(args, "length", None),
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
        "--retriever",
        choices=RETRIEVERS,
        default=None,
        help="ranking strategy (default: bm25; embedding and hybrid need docsage[embeddings])",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        default=None,
        help="let Claude reorder the best candidates before search and ask return them",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log debug events (key=value) to stderr"
    )
    commands = parser.add_subparsers(required=True)

    index = commands.add_parser("index", help="index files, folders or web pages")
    index.add_argument(
        "paths", nargs="+", metavar="path_or_url", help="a file, a folder or an http(s) URL"
    )
    index.add_argument(
        "--force", action="store_true", help="re-index files even if they have not changed"
    )
    index.add_argument(
        "--chunker",
        choices=list(CHUNKERS),
        default=None,
        help="window: fixed word windows (default); sentence: whole sentences only",
    )
    index.set_defaults(handler=_index)

    watch = commands.add_parser(
        "watch", help="index folders, then keep the index in sync as their files change"
    )
    watch.add_argument("paths", nargs="+", type=Path, metavar="path", help="a file or a folder")
    watch.add_argument(
        "--interval",
        type=_interval,
        default=1.0,
        help="seconds between looks at the files (default: 1)",
    )
    watch.add_argument(
        "--chunker",
        choices=list(CHUNKERS),
        default=None,
        help="window: fixed word windows (default); sentence: whole sentences only",
    )
    watch.set_defaults(handler=_watch)

    remove = commands.add_parser("remove", help="drop a file, folder or web page from the index")
    remove.add_argument(
        "path", metavar="path_or_url", help="a file, a folder, or a URL (also drops pages below it)"
    )
    remove.set_defaults(handler=_remove)

    search = commands.add_parser("search", help="show the best matching chunks")
    search.add_argument("query")
    search.add_argument("-k", "--top-k", type=int, default=5)
    search.add_argument("--json", action="store_true", help="print results as JSON")
    search.add_argument(
        "--explain", action="store_true", help="show how much each query term adds to the score"
    )
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

    evaluate = commands.add_parser(
        "evaluate", help="measure recall@k and MRR of the retriever on labeled queries"
    )
    evaluate.add_argument(
        "labels", type=Path, help='JSON list of {"query": ..., "relevant": [sources]}'
    )
    evaluate.add_argument("-k", "--top-k", type=int, default=5, help="cut-off (default: 5)")
    evaluate.add_argument(
        "--format",
        choices=sorted([*EVALUATION_FORMATS, "json"]),
        default="text",
        help="default: text",
    )
    evaluate.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="file to write (default: print to stdout)",
    )
    evaluate.set_defaults(handler=_evaluate)

    ask = commands.add_parser("ask", help="answer a question with Claude")
    ask.add_argument("question")
    ask.add_argument("-k", "--top-k", type=int, default=5)
    ask.add_argument("--model", default=None)
    _add_style_arguments(ask)
    ask.add_argument("--json", action="store_true", help="print the answer as JSON")
    ask.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        help="print the answer only once it is complete instead of as it is written",
    )
    _add_usage_argument(ask)
    ask.set_defaults(handler=_ask)

    chat = commands.add_parser(
        "chat", help="talk with Claude about your documents, follow-up questions included"
    )
    chat.add_argument("-k", "--top-k", type=int, default=5)
    chat.add_argument("--model", default=None)
    _add_style_arguments(chat)
    _add_usage_argument(chat)
    chat.set_defaults(handler=_chat)

    report = commands.add_parser(
        "report", help="answer a question with Claude and write an HTML report"
    )
    report.add_argument("question")
    report.add_argument("-k", "--top-k", type=int, default=5)
    report.add_argument("--model", default=None)
    _add_style_arguments(report)
    report.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="file to write (default: print to stdout)",
    )
    report.add_argument(
        "--format", choices=sorted(REPORT_FORMATS), default="html", help="default: html"
    )
    report.add_argument(
        "--open",
        action="store_true",
        help="open the report in the default browser (a temporary file unless -o is given)",
    )
    report.set_defaults(handler=_report)

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


def _add_style_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--language",
        default=None,
        help="language to answer in, e.g. Portuguese (default: the question's language)",
    )
    command.add_argument(
        "--length",
        choices=ANSWER_LENGTHS,
        default=None,
        help="short: a few sentences; long: every relevant detail (default: medium)",
    )


def _add_usage_argument(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--usage",
        action="store_true",
        help="after each answer, print the tokens it used and its estimated cost",
    )


def _index(container: Container, args: argparse.Namespace) -> int:
    service = container.indexing_service()
    urls = [target for target in args.paths if is_url(target)]
    paths = [Path(target) for target in args.paths if not is_url(target)]
    report = service.index(expand_paths(paths), force=args.force)
    if urls:
        report = report.combined_with(service.index_urls(urls, force=args.force))
    print(f"Indexed {report.documents} documents into {report.chunks} chunks.")
    if report.unchanged:
        print(f"Skipped {report.unchanged} unchanged documents (use --force to re-index).")
    for path in report.skipped:
        print(f"  skipped (unsupported): {path}", file=sys.stderr)
    for url, reason in report.failed:
        print(f"  failed: {url}: {reason}", file=sys.stderr)
    return 1 if report.failed else 0


def _watch(container: Container, args: argparse.Namespace) -> int:
    missing = [str(path) for path in args.paths if not path.exists()]
    if missing:
        print(f"docsage: no such file or folder: {', '.join(missing)}", file=sys.stderr)
        return 2
    service = container.watch_service(args.interval)
    targets = ", ".join(str(path) for path in args.paths)
    print(f"Watching {targets} for changes (Ctrl-C to stop).", flush=True)
    try:
        for update in service.watch(args.paths):
            _print_watch_update(update)
    except KeyboardInterrupt:
        print("Stopped watching.")
    return 0


def _print_watch_update(update: WatchUpdate) -> None:
    report = update.indexing
    if report.documents:
        print(f"Indexed {report.documents} documents into {report.chunks} chunks.")
    for source in update.removed:
        print(f"Removed {source}.")
    for path in report.skipped:
        print(f"  skipped (unsupported): {path}", file=sys.stderr)
    sys.stdout.flush()


def _remove(container: Container, args: argparse.Namespace) -> int:
    service = container.removal_service()
    report = service.remove_url(args.path) if is_url(args.path) else service.remove(Path(args.path))
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
        if args.explain and result.contributions:
            print(f"   score = {breakdown(result.contributions)}")
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
    _write_output(content, args.output)
    return 0


def _evaluate(container: Container, args: argparse.Namespace) -> int:
    if args.top_k < 1:
        print("docsage: --top-k must be at least 1", file=sys.stderr)
        return 2
    try:
        cases = read_evaluation_set(args.labels)
    except EvaluationSetError as error:
        print(f"docsage: {error}", file=sys.stderr)
        return 2
    service = container.evaluation_service("text" if args.format == "json" else args.format)
    report = service.evaluate(cases, args.top_k)
    if args.format == "json":
        content = dumps(evaluation_to_dict(report)) + "\n"
    else:
        content = service.render(report)
    _write_output(content, args.output)
    return 0


def _report(container: Container, args: argparse.Namespace) -> int:
    report = container.answer_report_service(args.format).report(args.question, args.top_k)
    output: Path | None = args.output
    if output is None and args.open:
        output = Path(tempfile.mkdtemp(prefix="docsage-")) / f"report.{_EXTENSIONS[args.format]}"
    _write_output(report.content, output)
    if args.open and output is not None and not webbrowser.open(output.resolve().as_uri()):
        print(f"docsage: could not open a browser, the report is at {output}", file=sys.stderr)
    return 0


_EXTENSIONS = {"html": "html", "text": "txt"}


def _write_output(content: str, output: Path | None) -> None:
    """Prints ``content``, or writes it to ``output`` and says where."""
    if output is None:
        _write_stdout(content)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(f"Wrote {output}")


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
    service = container.question_answering_service()
    if args.json:
        print(dumps(answer_to_dict(service.ask(args.question, args.top_k))))
        return 0
    if args.stream:
        answer = service.ask(args.question, args.top_k, on_text=_write_piece)
        print()
    else:
        answer = service.ask(args.question, args.top_k)
        print(answer.text)
    _print_sources(answer.sources)
    if args.usage:
        _print_usage(answer)
    return 0


CHAT_HELP = "Ask a question. /reset starts a new conversation, /exit (or Ctrl-D) quits."


def _chat(container: Container, args: argparse.Namespace) -> int:
    service = container.chat_service()
    print(CHAT_HELP)
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue
        if question in ("/exit", "/quit"):
            return 0
        if question == "/reset":
            service.reset()
            print("Started a new conversation.")
            continue
        answer = service.ask(question, args.top_k, on_text=_write_piece)
        print()
        _print_sources(answer.sources)
        if args.usage:
            _print_usage(answer)


def _print_sources(sources: Sequence[SearchResult]) -> None:
    if sources:
        print("\nSources:")
        for index, result in enumerate(sources, start=1):
            print(f"  [{index}] {result.chunk.citation}")


def _print_usage(answer: Answer) -> None:
    if answer.usage is not None:
        print(f"\nUsage: {usage_summary(answer.usage, answer.cost_usd)}")


def _write_piece(text: str) -> None:
    _write_stdout(text)
    sys.stdout.flush()


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


def _interval(value: str) -> float:
    seconds = float(value)
    if seconds <= 0:
        raise argparse.ArgumentTypeError(f"interval must be positive, got {value}")
    return seconds


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port must be between 1 and 65535, got {port}")
    return port


if __name__ == "__main__":
    raise SystemExit(main())
