"""Checks that a release tag matches the package version before anything is published.

    python scripts/check_release.py v0.7.0

The tag defaults to ``GITHUB_REF_NAME``, which GitHub Actions sets to the pushed tag. The
version is read from ``src/docsage/__init__.py`` as text, so the package need not be
installed. Exits with status 1 and a reason when the tag is not ``v<version>`` or the
version is not a plain ``MAJOR.MINOR.PATCH`` release.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "src" / "docsage" / "__init__.py"
RELEASE_VERSION = re.compile(r"\d+\.\d+\.\d+")
VERSION_LINE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def package_version(init_file: Path = PACKAGE_INIT) -> str:
    found = VERSION_LINE.search(init_file.read_text(encoding="utf-8"))
    if found is None:
        raise ValueError(f"no __version__ in {init_file}")
    return found.group(1)


def release_problem(tag: str, version: str) -> str | None:
    """Returns why ``tag`` must not be released as ``version``, or None when it may."""
    if not RELEASE_VERSION.fullmatch(version):
        return f"package version {version!r} is not a MAJOR.MINOR.PATCH release"
    if tag != f"v{version}":
        return f"tag {tag!r} does not match the package version (expected 'v{version}')"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    tag = args[0] if args else os.environ.get("GITHUB_REF_NAME", "")
    if not tag:
        print("usage: check_release.py <tag> (or set GITHUB_REF_NAME)", file=sys.stderr)
        return 2
    version = package_version()
    problem = release_problem(tag, version)
    if problem is not None:
        print(f"Refusing to release: {problem}", file=sys.stderr)
        return 1
    print(f"Releasing docsage {version} from tag {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
