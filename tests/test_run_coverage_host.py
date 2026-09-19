from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_coverage_host.py"
SPEC = importlib.util.spec_from_file_location("run_coverage_host", MODULE_PATH)
assert SPEC is not None
run_coverage_host = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(run_coverage_host)


def test_cov_source_args_multiline_coveragerc_source(tmp_path: Path) -> None:
    (tmp_path / ".coveragerc").write_text(
        """
[run]
source =
    api
    audit
    consumers
    db
    schemas
    scripts
    services
    worker
    alembic
""",
        encoding="utf-8",
    )

    assert run_coverage_host._cov_source_args(tmp_path) == [
        "--cov=api",
        "--cov=audit",
        "--cov=consumers",
        "--cov=db",
        "--cov=schemas",
        "--cov=scripts",
        "--cov=services",
        "--cov=worker",
        "--cov=alembic",
    ]


def test_cov_source_args_comma_separated_coveragerc_source(tmp_path: Path) -> None:
    (tmp_path / ".coveragerc").write_text(
        """
[run]
source = api, audit, services
""",
        encoding="utf-8",
    )

    assert run_coverage_host._cov_source_args(tmp_path) == [
        "--cov=api",
        "--cov=audit",
        "--cov=services",
    ]


def test_cov_source_args_src_fallback(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()

    assert run_coverage_host._cov_source_args(tmp_path) == ["--cov=src"]


def test_cov_source_args_dot_fallback(tmp_path: Path) -> None:
    assert run_coverage_host._cov_source_args(tmp_path) == ["--cov=."]


def test_cov_source_args_tool_images_special_case(tmp_path: Path) -> None:
    repo = tmp_path / "omnibioai-tool-images"
    (repo / "api").mkdir(parents=True)
    (repo / ".coveragerc").write_text(
        """
[run]
source = scripts
""",
        encoding="utf-8",
    )

    assert run_coverage_host._cov_source_args(repo) == ["--cov=api"]


def test_cov_source_args_pyproject_coverage_source_precedes_coveragerc(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.coverage.run]
source = ["control_center", "scripts"]
""",
        encoding="utf-8",
    )
    (tmp_path / ".coveragerc").write_text(
        """
[run]
source = api
""",
        encoding="utf-8",
    )

    assert run_coverage_host._cov_source_args(tmp_path) == [
        "--cov=control_center",
        "--cov=scripts",
    ]
