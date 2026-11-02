# Contributing

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy          # strict type checking of src/, also run in CI
pytest --cov  # coverage report; CI fails below 90% and publishes the summary
```

`tests/unit/` covers each class with fakes. `tests/integration/` drives the MCP server
end to end: one in-memory client session indexes the small corpus in
`tests/fixtures/corpus/`, reads resources, searches, asks and removes, against a real
on-disk index. Only the answer generator is faked (`Container(settings, generator)`),
so no test calls the Claude API.

Pushing a `vX.Y.Z` tag runs the `Release` workflow, which checks that the tag matches
`docsage.__version__`, builds the package and publishes it to PyPI (see
[CONTRIBUTING.md](#releasing)).

## Branching (git flow)

| Branch        | Purpose                                              |
| ------------- | ---------------------------------------------------- |
| `main`        | Released code only. Every merge is tagged `vX.Y.Z`.  |
| `develop`     | Integration branch. Features merge here.             |
| `feature/*`   | One feature or fix, branched from `develop`.         |
| `release/*`   | Version bump and changelog, merged to `main` and `develop`. |
| `hotfix/*`    | Urgent fix branched from `main`.                     |

Features are merged with `git merge --no-ff` so the history keeps the feature boundary.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/), in English:

```
feat(retrieval): add hybrid BM25 + embedding search
fix(loaders): handle PDFs with empty pages
test(chunking): cover overlap edge cases
docs: document the index format
refactor(cli): extract output formatting
```

Keep each commit small and focused. Tests and lint must pass before a commit.

## Architecture

The code follows a ports-and-adapters (hexagonal) layout:

```
src/docsage/
├── domain/           entities (Document, Chunk, Answer) and ports (Protocols)
├── application/      use cases: indexing, removal, stats, question answering, reports
├── infrastructure/   adapters: file loaders, chunker, BM25 retriever, Claude generator,
│                     HTML and plain-text renderers
├── interfaces/       CLI, MCP server and shared JSON serializers
└── container.py      composition root, wires adapters to ports
```

- **Single responsibility.** Each adapter does one job: loading, chunking, ranking or generating.
- **Open/closed.** New file formats or retrievers are new classes that implement a port. Existing code stays untouched.
- **Dependency inversion.** Use cases depend on the Protocols in `domain/ports.py`, never on concrete adapters. That is why the tests can swap in fakes without mocking libraries.

## Architecture rules

- `domain` imports nothing from the other layers.
- `application` imports only from `domain`.
- `infrastructure` implements ports from `domain`.
- Only `container.py` and `interfaces` know about concrete adapters.

## Releasing

Releases are cut by the maintainer from `main`:

1. On a `release/X.Y.Z` branch, set `__version__` in `src/docsage/__init__.py` (the only
   place the version lives; `pyproject.toml` reads it from there).
2. Merge to `main` and `develop`, then tag the merge on `main` as `vX.Y.Z` and push the tag.
3. The `Release` workflow runs the tests, checks the tag with
   `python scripts/check_release.py`, builds the sdist and wheel, and publishes them to
   PyPI with trusted publishing.

PyPI must list this repository's `release.yml` workflow and the `pypi` environment as a
trusted publisher before the first release; no API token is stored in GitHub.
