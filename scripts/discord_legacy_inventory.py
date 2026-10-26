#!/usr/bin/env python3
"""Read-only offline inventory of legacy Discord publication references."""

from __future__ import annotations

import re
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {
    ".git", ".pytest_cache", ".venv", ".workstreams", ".worktrees", "venv",
    "node_modules", "build", "coverage", "dist", "dist-releases", "__pycache__",
}
TEXT_SUFFIXES = {
    "", ".c", ".cfg", ".env", ".example", ".html", ".ini", ".js", ".json",
    ".md", ".py", ".sh", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
}
CHECKS = (
    ("webhook-url-literal", re.compile(r"discord(?:app)?\.com/api(?:/v\d+)?/webhooks", re.I)),
    ("legacy-env-reference", re.compile(r"\bDISCORD_WEBHOOK_URL\b")),
    ("direct-http-post", re.compile(
        r"(?:httpx|requests|urllib\.request)\s*\.\s*(?:post|urlopen)\s*\([^\n]*(?:discord|webhook)|"
        r"\bcurl\b[^\n]*(?:discord|webhook)", re.I,
    )),
)


def repository_for(path: Path) -> str:
    current = path.parent
    while current != ROOT and current.parent != current:
        if (current / ".git").exists():
            return current.name
        current = current.parent
    return ROOT.name


def iter_findings(root: Path = ROOT):
    repositories = sorted(
        path for path in root.iterdir() if path.is_dir() and (path / ".git").exists()
    )
    for repository in repositories:
      for directory, dirnames, filenames in os.walk(repository):
        parent = Path(directory)
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in SKIP_DIRS and not (parent.name == "docs" and name == "evidence")
        )
        for filename in sorted(filenames):
            path = parent / filename
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            relative = path.relative_to(root)
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for number, line in enumerate(lines, start=1):
                for kind, pattern in CHECKS:
                    if pattern.search(line):
                        yield repository_for(path), relative, number, kind


def main() -> int:
    print("repo\tlocation\tkind")
    for repo, path, line, kind in iter_findings():
        print(f"{repo}\t{path}:{line}\t{kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
