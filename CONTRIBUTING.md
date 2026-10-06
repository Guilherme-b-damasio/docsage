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
