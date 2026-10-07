import logging

import pytest

from docsage.infrastructure.logs import ROOT_LOGGER


@pytest.fixture(autouse=True)
def _restore_docsage_logger():
    """Undo ``configure_logging`` so one test's handler never leaks into the next."""
    logger = logging.getLogger(ROOT_LOGGER)
    handlers, level = list(logger.handlers), logger.level
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)
