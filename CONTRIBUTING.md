# Contributing

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
