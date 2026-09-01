# omnibioai-control-center/scripts/run_coverage_host.py

#!/usr/bin/env python3
"""
run_coverage_host.py — Run test coverage for each OmniBioAI repo on the host.

Runs on the developer machine (not inside the control-center container) so each
repo's dependencies are already installed.  Saves a per-repo result JSON to:

  ${WORK_DIR}/out/coverage/<repo_name>.json

The control-center container reads those files (via the /workspace volume mount)
instead of running pytest itself, which would fail due to missing package installs.

Usage
-----
  # From anywhere:
  python3 ~/Desktop/machine/omnibioai-control-center/scripts/run_coverage_host.py

  # Custom root:
  python3 .../run_coverage_host.py --root ~/Desktop/machine

  # Specific repos only:
  python3 .../run_coverage_host.py --repos omnibioai-tes omnibioai_sdk

After running, click Regenerate in the Control Center UI to rebuild the report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


# --------------------------------------------------------------------------- #
# Repos — same list as generate_report.py DEFAULT_TARGETS
# --------------------------------------------------------------------------- #

REPOS = [
    # Core services
    "omnibioai-tes",
    "omnibioai-workbench",
    "omnibioai-rag",
    "omnibioai-lims",
    "omnibioai-toolserver",
    "omnibioai-tool-runtime",
    "omnibioai-control-center",
    "omnibioai-sdk",
    "omnibioai-design-tokens",
    "omnibioai-workflow-bundles",
    "omnibioai-model-registry",
    "omnibioai-tool-images",
    "omnibioai-dev-hub",
    "omnibioai-videos",
    "omnibioai-launcher",
    "omnibioai-docs",
    "omnibioai-usage-client",
    "omnibioai-billing",
    # Security plane
    "omnibioai-auth",
    "omnibioai-api-gateway",
    "omnibioai-policy-engine",
    "omnibioai-hpc-policy-engine",
    "omnibioai-security-audit",
    "omnibioai-security-sdk",
    "omnibioai-iam-client",
]

# Repos that need more than the default 300s timeout
REPO_TIMEOUTS: Dict[str, int] = {
    "omnibioai": 3600,          # 60 min — 200+ plugins each with tests
    "omnibioai-tool-images": 300,
}

DEFAULT_TIMEOUT = 3600


# --------------------------------------------------------------------------- #
# Helpers — mirrors generate_report.py logic so results are consistent
# --------------------------------------------------------------------------- #

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _has_pytest_project(repo: Path) -> bool:
    return (
        (repo / "pyproject.toml").exists()
        or (repo / "pytest.ini").exists()
        or (repo / "tests").exists()
        or (repo / "backend" / "pyproject.toml").exists()
    )


def _has_npm_coverage_project(repo: Path) -> bool:
    """Return whether the repo exposes the standard npm coverage command."""
    package_file = repo / "package.json"
    if not package_file.exists():
        return False
    try:
        package = json.loads(package_file.read_text(encoding="utf-8"))
        script = package.get("scripts", {}).get("test:coverage")
        return isinstance(script, str) and bool(script.strip())
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def _pytest_cwd(repo: Path) -> Path:
    if (repo / "backend" / "pyproject.toml").exists():
        return repo / "backend"
    return repo


def _cov_source_args(cwd: Path) -> List[str]:
    text = _read_text(cwd / "pyproject.toml")
    if text:
        m = re.search(r'\[tool\.coverage\.run\](.*?)(?=\n\[|\Z)', text, re.DOTALL)
        if m:
            sm = re.search(r'^source\s*=\s*\[([^\]]*)\]', m.group(1), re.MULTILINE)
            if sm:
                sources = re.findall(r'["\']([^"\']+)["\']', sm.group(1))
                if sources:
                    return [f"--cov={s}" for s in sources]

    text = _read_text(cwd / ".coveragerc")
    if text:
        m = re.search(r'\[run\](.*?)(?=\n\[|\Z)', text, re.DOTALL)
        if m:
            sm = re.search(r'^source\s*=\s*(.+?)$', m.group(1), re.MULTILINE)
            if sm:
                sources = [s.strip() for s in sm.group(1).split(',') if s.strip()]
                if sources:
                    return [f"--cov={s}" for s in sources]

    if (cwd / "src").is_dir():
        return ["--cov=src"]
    return ["--cov=."]


def _subprocess_env(cwd: Path) -> dict:
    env = os.environ.copy()
    for cfg_path in [
        cwd / "pytest.ini", cwd / "setup.cfg",
        cwd.parent / "pytest.ini", cwd.parent / "setup.cfg",
    ]:
        if not cfg_path.exists():
            continue
        text = _read_text(cfg_path)
        m = re.search(r"DJANGO_SETTINGS_MODULE\s*[=:]\s*(\S+)", text)
        if m:
            env.setdefault("DJANGO_SETTINGS_MODULE", m.group(1))
            break
    return env


def _extract_total_line(output: str) -> Optional[str]:
    for line in output.splitlines():
        if re.match(r"^\s*TOTAL\b", line):
            return line.strip()
    return None


def _parse_total_line(total_line: str) -> Dict[str, Any]:
    parts = re.split(r"\s+", total_line.strip())
    nums = parts[1:]
    if len(nums) == 3:
        stmts, miss, cover = nums
        return {"statements": int(stmts), "missed": int(miss),
                "branches": None, "partial_branches": None,
                "coverage_pct": float(cover.rstrip("%"))}
    if len(nums) == 5:
        stmts, miss, branches, bpart, cover = nums
        return {"statements": int(stmts), "missed": int(miss),
                "branches": int(branches), "partial_branches": int(bpart),
                "coverage_pct": float(cover.rstrip("%"))}
    return {}


def _parse_coverage_json(cwd: Path) -> Optional[Dict[str, Any]]:
    cov_file = cwd / "coverage.json"
    if not cov_file.exists():
        return None
    try:
        data = json.loads(cov_file.read_text(encoding="utf-8"))
        totals = data.get("totals", {})
        pct   = totals.get("percent_covered")
        stmts = totals.get("num_statements")
        if pct is None or stmts is None:
            return None
        return {
            "statements":       int(stmts),
            "missed":           int(totals.get("missing_lines") or 0),
            "branches":         totals.get("num_partial_branches"),
            "partial_branches": None,
            "coverage_pct":     round(float(pct), 2),
        }
    except Exception:
        return None


def _parse_vitest_coverage_json(cwd: Path) -> Optional[Dict[str, Any]]:
    """Parse Vitest's coverage-summary or coverage-final JSON output."""
    summary_file = cwd / "coverage" / "coverage-summary.json"
    if summary_file.exists():
        try:
            total = json.loads(summary_file.read_text(encoding="utf-8")).get("total", {})
            statements = total.get("statements", {})
            branches = total.get("branches", {})
            if statements.get("total") is not None:
                return {
                    "statements": int(statements["total"]),
                    "missed": int(statements.get("total", 0) - statements.get("covered", 0)),
                    "branches": int(branches["total"]) if branches.get("total") is not None else None,
                    "partial_branches": int(branches.get("total", 0) - branches.get("covered", 0)) if branches.get("total") is not None else None,
                    "coverage_pct": round(float(statements.get("pct", 0)), 2),
                }
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass

    final_file = cwd / "coverage" / "coverage-final.json"
    if not final_file.exists():
        return None
    try:
        data = json.loads(final_file.read_text(encoding="utf-8"))
        statements = covered_statements = branches = covered_branches = 0
        for file_data in data.values():
            statement_counts = file_data.get("s", {})
            statements += len(statement_counts)
            covered_statements += sum(1 for count in statement_counts.values() if count > 0)
            for counts in file_data.get("b", {}).values():
                branches += len(counts)
                covered_branches += sum(1 for count in counts if count > 0)
        if statements == 0:
            return None
        return {
            "statements": statements,
            "missed": statements - covered_statements,
            "branches": branches or None,
            "partial_branches": (branches - covered_branches) if branches else None,
            "coverage_pct": round(covered_statements / statements * 100, 2),
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _resolve_repo(root: Path, name: str) -> Path:
    exact = root / name
    if exact.is_dir():
        return exact
    norm_key = name.lower().replace("-", "_")
    for entry in root.iterdir():
        if entry.is_dir() and entry.name.lower().replace("-", "_") == norm_key:
            return entry
    return exact


def run_npm_repo(repo: Path, timeout_override: int | None = None) -> Dict[str, Any]:
    """Run a repository's test:coverage script and normalize its result."""
    result: Dict[str, Any] = {
        "repo": repo.name, "path": str(repo),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "returncode": None, "statements": None, "missed": None,
        "branches": None, "partial_branches": None, "coverage_pct": None,
        "total_line": None, "stdout_tail": None, "stderr_tail": None,
        "status": "ok",
    }
    timeout = timeout_override or REPO_TIMEOUTS.get(repo.name, DEFAULT_TIMEOUT)
    print(f"    npm run test:coverage (timeout={timeout}s) …", end=" ", flush=True)
    try:
        proc = subprocess.run(
            ["npm", "run", "test:coverage"], cwd=str(repo), env=_subprocess_env(repo),
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        result["status"] = "timeout"
        result["stderr_tail"] = str(exc)
        print("timeout")
        return result
    print(f"rc={proc.returncode}")
    result["returncode"] = proc.returncode
    result["stdout_tail"] = "\n".join(proc.stdout.strip().splitlines()[-50:]) or None
    result["stderr_tail"] = "\n".join(proc.stderr.strip().splitlines()[-10:]) or None
    cov_data = _parse_vitest_coverage_json(repo)
    if cov_data:
        result.update(cov_data)
        result["total_line"] = "vitest-json"
        result["status"] = "ok" if proc.returncode == 0 else "test_failure"
    else:
        result["status"] = "no_total_found" if proc.returncode == 0 else "test_failure"
    return result


# --------------------------------------------------------------------------- #
# Per-repo runner
# --------------------------------------------------------------------------- #

def run_repo(repo: Path, timeout_override: int | None = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "repo":             repo.name,
        "path":             str(repo),
        "generated_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "returncode":       None,
        "statements":       None,
        "missed":           None,
        "branches":         None,
        "partial_branches": None,
        "coverage_pct":     None,
        "total_line":       None,
        "stdout_tail":      None,
        "stderr_tail":      None,
        "status":           "ok",
    }

    if not repo.exists():
        result["status"] = "missing_path"
        return result

    if _has_npm_coverage_project(repo):
        return run_npm_repo(repo, timeout_override)

    if not _has_pytest_project(repo):
        result["status"] = "skipped_no_pytest_project"
        return result

    cwd      = _pytest_cwd(repo)
    cov_args = _cov_source_args(cwd)
    env      = _subprocess_env(cwd)

    # Install the package in editable mode so its own imports resolve.
    # --no-deps: host already has deps; we just need the importable package.
    if (cwd / "pyproject.toml").exists():
        print(f"    pip install -e . --no-deps …", end=" ", flush=True)
        pip = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet", "--no-deps"],
            cwd=str(cwd), capture_output=True, timeout=120,
        )
        print("ok" if pip.returncode == 0 else f"WARN rc={pip.returncode}")

    cmd = [
        sys.executable, "-m", "pytest",
        *cov_args,
        "--cov-report=term-missing", "--cov-report=json",
        "--tb=no", "-q",
        "-p", "no:cacheprovider",
        "--continue-on-collection-errors",
        "--ignore=node_modules",
    ]
    timeout = timeout_override or REPO_TIMEOUTS.get(repo.name, DEFAULT_TIMEOUT)
    print(f"    pytest {' '.join(cov_args)} (timeout={timeout}s) …", end=" ", flush=True)
    proc = subprocess.run(
        cmd, cwd=str(cwd), env=env,
        capture_output=True, text=True, timeout=timeout,
    )
    print(f"rc={proc.returncode}")

    result["returncode"] = proc.returncode

    # Capture tails for status classification in generate_report.py
    stdout_lines = proc.stdout.strip().splitlines()
    stderr_lines = proc.stderr.strip().splitlines()
    result["stdout_tail"] = "\n".join(stdout_lines[-50:]) if stdout_lines else None
    result["stderr_tail"] = "\n".join(stderr_lines[-10:]) if stderr_lines else None

    total_line = _extract_total_line(proc.stdout)
    cov_data   = None
    if not total_line:
        cov_data = _parse_coverage_json(cwd)

    if total_line:
        result["total_line"] = total_line
        result.update(_parse_total_line(total_line))
    elif cov_data:
        result["total_line"] = "json"
        result.update(cov_data)
    else:
        result["status"] = "no_total_found"

    if proc.returncode != 0 and result["status"] == "ok":
        result["status"] = "test_failure"

    return result


# --------------------------------------------------------------------------- #
# omnibioai special handler — two-domain coverage (services + plugins)
# --------------------------------------------------------------------------- #

def run_omnibioai(repo: Path, timeout_override: int | None = None) -> Dict[str, Any]:
    """
    Special handler for omnibioai — runs two separate pytest domains
    (services + plugins) and merges their coverage, matching run_coverage.sh.
    """
    result: Dict[str, Any] = {
        "repo":             repo.name,
        "path":             str(repo),
        "generated_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "returncode":       None,
        "statements":       None,
        "missed":           None,
        "branches":         None,
        "partial_branches": None,
        "coverage_pct":     None,
        "total_line":       None,
        "stdout_tail":      None,
        "stderr_tail":      None,
        "status":           "ok",
    }

    if not repo.exists():
        result["status"] = "missing_path"
        return result

    env = _subprocess_env(repo)
    timeout = timeout_override or REPO_TIMEOUTS.get(repo.name, 3600)

    # ── Domain 1: services ────────────────────────────────────────────
    print(f"    [1/2] services (timeout={timeout}s) …", end=" ", flush=True)
    svc_cmd = [
        sys.executable, "-m", "pytest", "tests/",
        "--ignore=tests/test_performance_baselines.py",
        "--ignore=tests/utils/",
        "--cov=omnibioai/services",
        "--cov-report=json:coverage_services.json",
        "--cov-report=term-missing",
        "--tb=no", "-q",
        "-p", "no:cacheprovider",
        "--continue-on-collection-errors",
    ]
    svc_proc = subprocess.run(
        svc_cmd, cwd=str(repo), env=env,
        capture_output=True, text=True, timeout=timeout,
    )
    print(f"rc={svc_proc.returncode}")

    # ── Domain 2: plugins ─────────────────────────────────────────────
    print(f"    [2/2] plugins (timeout={timeout}s) …", end=" ", flush=True)
    plg_cmd = [
        sys.executable, "-m", "pytest", "plugins/",
        "--cov=plugins",
        "--cov-report=json:coverage_plugins.json",
        "--cov-report=term-missing",
        "--tb=no", "-q",
        "-p", "no:cacheprovider",
        "--continue-on-collection-errors",
    ]
    plg_proc = subprocess.run(
        plg_cmd, cwd=str(repo), env=env,
        capture_output=True, text=True, timeout=timeout,
    )
    print(f"rc={plg_proc.returncode}")

    result["returncode"] = max(svc_proc.returncode, plg_proc.returncode)
    result["stdout_tail"] = (
        (svc_proc.stdout.strip() + "\n" + plg_proc.stdout.strip())[-2000:]
    )
    result["stderr_tail"] = (
        (svc_proc.stderr.strip() + "\n" + plg_proc.stderr.strip())[-500:]
    )

    # ── Merge coverage JSON files ─────────────────────────────────────
    try:
        svc_data = json.loads((repo / "coverage_services.json").read_text())
        plg_data = json.loads((repo / "coverage_plugins.json").read_text())

        svc_totals = svc_data.get("totals", {})
        plg_totals = plg_data.get("totals", {})

        total_stmts   = (svc_totals.get("num_statements", 0) +
                         plg_totals.get("num_statements", 0))
        total_covered = (svc_totals.get("covered_lines", 0) +
                         plg_totals.get("covered_lines", 0))
        total_missing = (svc_totals.get("missing_lines", 0) +
                         plg_totals.get("missing_lines", 0))
        total_pct     = (total_covered / total_stmts * 100
                         if total_stmts else 0.0)

        result["statements"]   = total_stmts
        result["missed"]       = total_missing
        result["coverage_pct"] = round(total_pct, 2)
        result["total_line"]   = "merged:services+plugins"
        result["status"]       = "ok"

        print(f"    → merged: {total_covered}/{total_stmts} = {total_pct:.2f}%")

    except Exception as e:
        result["status"] = "no_total_found"
        print(f"    → merge failed: {e}")

    return result


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--root", type=Path,
        default=Path.home() / "Desktop/machine",
        help="Ecosystem root (default: ~/Desktop/machine)",
    )
    parser.add_argument(
        "--repos", nargs="+", default=None,
        help="Repo names to process (default: all)",
    )
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="Override timeout in seconds for all repos (default: per-repo config)",
    )
    args = parser.parse_args()

    root     = args.root.resolve()
    repos    = args.repos or REPOS
    work_dir = Path(os.environ.get("WORK_DIR", str(root / "work")))
    out_dir  = work_dir / "out" / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Root   : {root}")
    print(f"Output : {out_dir}")
    print(f"Python : {sys.executable}")
    print()

    ok = warn = skip = 0
    for name in repos:
        repo = _resolve_repo(root, name)
        print(f"[{repo.name}]")

        # omnibioai needs special two-domain coverage collection
        if repo.name == "omnibioai":
            result = run_omnibioai(repo, timeout_override=args.timeout)
        else:
            result  = run_repo(repo, timeout_override=args.timeout)
        out_f   = out_dir / f"{repo.name}.json"
        out_f.write_text(json.dumps(result, indent=2), encoding="utf-8")

        pct    = result.get("coverage_pct")
        status = result["status"]
        suffix = f", {pct:.2f}%" if pct is not None else ""
        print(f"    → {status}{suffix}  →  {out_f.name}")
        print()

        if status == "ok":
            ok += 1
        elif status.startswith("skipped") or status == "missing_path":
            skip += 1
        else:
            warn += 1

    print(f"Done — {ok} ok, {warn} with issues, {skip} skipped")
    print(f"Regenerate the report at http://localhost:7070 to see results.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
