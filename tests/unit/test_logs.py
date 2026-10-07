import io
import logging

from docsage.infrastructure.logs import KeyValueFormatter, configure_logging


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.makeLogRecord({"name": "docsage.test", "levelname": "INFO", "msg": message})
    record.__dict__.update(extra)
    return record


def test_formatter_renders_extra_fields_as_key_value_pairs():
    line = KeyValueFormatter().format(_record("indexed", source="a.md", chunks=3))
    assert line == 'level=info logger=docsage.test event=indexed source=a.md chunks=3'


def test_formatter_quotes_values_with_spaces_and_quotes():
    line = KeyValueFormatter().format(_record("search done", query='say "hi" now'))
    assert 'event="search done"' in line
    assert 'query="say \\"hi\\" now"' in line


def test_configure_logging_hides_debug_unless_verbose():
    stream = io.StringIO()
    logger = configure_logging(verbose=False, stream=stream)
    logger.getChild("x").debug("hidden")
    logger.getChild("x").warning("shown")
    assert "hidden" not in stream.getvalue()
    assert "event=shown" in stream.getvalue()

    stream = io.StringIO()
    configure_logging(verbose=True, stream=stream).getChild("x").debug("visible")
    assert "level=debug logger=docsage.x event=visible" in stream.getvalue()


def test_configure_logging_does_not_stack_handlers():
    configure_logging(stream=io.StringIO())
    logger = configure_logging(stream=io.StringIO())
    assert sum(getattr(h, "_docsage", False) for h in logger.handlers) == 1


def test_formatter_appends_the_traceback_of_logged_exceptions():
    stream = io.StringIO()
    logger = configure_logging(stream=stream)
    try:
        raise ValueError("broken index")
    except ValueError:
        logger.getChild("x").exception("load failed", extra={"path": "index.json"})

    first, *rest = stream.getvalue().splitlines()
    assert first == "level=error logger=docsage.x event=\"load failed\" path=index.json"
    assert rest[-1] == "ValueError: broken index"


def test_formatter_quotes_empty_values():
    assert KeyValueFormatter().format(_record("x", note="")).endswith('note=""')


def test_configure_logging_keeps_handlers_it_did_not_add():
    logger = logging.getLogger("docsage")
    foreign = logging.NullHandler()
    logger.addHandler(foreign)
    configure_logging(stream=io.StringIO())
    assert foreign in logger.handlers
