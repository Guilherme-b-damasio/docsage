# docsage: the HTTP API with its web UI by default; the MCP server and the CLI are one
# command away (see the README's Docker section).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Optional extras to install, comma separated; add "embeddings" for the embedding and
# hybrid retrievers (it pulls in PyTorch, so the image grows by a few GB).
ARG EXTRAS=api,mcp,pdf

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[${EXTRAS}]" && rm -rf /src

# Run unprivileged. /data is the working directory, so the index lands in
# /data/.docsage/index.json and a docsage.toml placed there is picked up.
RUN useradd --create-home --uid 1000 docsage \
    && mkdir /data \
    && chown docsage:docsage /data
USER docsage
WORKDIR /data
VOLUME ["/data"]

EXPOSE 8000 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

ENTRYPOINT ["docsage"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
