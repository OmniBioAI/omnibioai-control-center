"""Compile the Control Center Python sources, excluding one known artifact.

``backend/src/control_center/combined_control_center.py`` is a tracked text
concatenation with ``===== FILE: ... =====`` separators, not an importable
module. The exact path is excluded only while its first section marker is
present. Every other Python file under the application, test, and script roots
must compile.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = Path("backend/src/control_center/combined_control_center.py")
SOURCE_ROOTS = (Path("backend/src"), Path("backend/tests"), Path("scripts"))


def main() -> int:
    excluded = ROOT / ARTIFACT
    if not excluded.is_file() or not excluded.read_text(encoding="utf-8").lstrip().startswith(
        "===== FILE: main.py ====="
    ):
        raise RuntimeError(f"Known concatenation artifact changed: {ARTIFACT}")

    count = 0
    for source_root in SOURCE_ROOTS:
        for path in sorted((ROOT / source_root).rglob("*.py")):
            if path == excluded:
                continue
            compile(path.read_bytes(), str(path.relative_to(ROOT)), "exec")
            count += 1
    print(f"Compiled {count} Python source files; excluded only {ARTIFACT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
