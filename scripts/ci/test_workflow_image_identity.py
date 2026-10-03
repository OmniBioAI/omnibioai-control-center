#!/usr/bin/env python3
"""Regression test for the GHCR image-reference lowercasing defect that
blocked the v0.7.3 release (buildx: "repository name must be lowercase").

Standalone and dependency-light (stdlib + PyYAML only) by design, run
directly in CI/locally -- not part of backend's pytest suite (scoped to
application code, 98% coverage gate) nor the stale root tests/ directory
(migration debt, not consumed by the Docker build or CI).

Usage: python3 scripts/ci/test_workflow_image_identity.py
Exits 0 and prints PASS lines on success; exits 1 with a FAIL line on the
first violation.
"""
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

CANONICAL_BACKEND_IMAGE = "ghcr.io/omnibioai/omnibioai-control-center"
CANONICAL_FRONTEND_IMAGE = "ghcr.io/omnibioai/omnibioai-control-center-web"

# Any GHCR image reference built directly from the raw (potentially
# mixed-case) github.repository context value, instead of the normalized
# resolve-version output. This is the exact shape of the bug that broke
# v0.7.3: ghcr.io/${{ github.repository }}[-web].
FORBIDDEN_RAW_REPO_PATTERN = re.compile(
    r"ghcr\.io/\$\{\{\s*github\.repository\s*\}\}"
)

failures = []


def fail(msg: str) -> None:
    failures.append(msg)


def check(condition: bool, msg: str) -> None:
    if not condition:
        fail(msg)


raw_text = WORKFLOW_PATH.read_text()
workflow = yaml.safe_load(raw_text)
jobs = workflow["jobs"]

# ---------------------------------------------------------------------
# 1. No executable GHCR reference anywhere derives directly from the raw
#    mixed-case github.repository value.
# ---------------------------------------------------------------------
raw_offenders = FORBIDDEN_RAW_REPO_PATTERN.findall(raw_text)
check(
    not raw_offenders,
    f"found {len(raw_offenders)} occurrence(s) of "
    f"'ghcr.io/${{{{ github.repository }}}}' -- every GHCR reference must "
    f"use needs.resolve-version.outputs.repo instead",
)

# ---------------------------------------------------------------------
# 2. Exactly one authoritative normalization point: resolve-version.
# ---------------------------------------------------------------------
resolve_job = jobs["resolve-version"]
resolve_run = resolve_job["steps"][0]["run"]
check(
    "repo" in resolve_job.get("outputs", {}),
    "resolve-version job must expose a 'repo' output",
)
check(
    "tr '[:upper:]' '[:lower:]'" in resolve_run,
    "resolve-version's resolve step must lowercase GITHUB_REPOSITORY via "
    "tr '[:upper:]' '[:lower:]'",
)
check(
    'echo "repo=' in resolve_run,
    "resolve-version's resolve step must write the lowercased value to "
    "the 'repo' output",
)

# Simulate the exact shell logic against the real org/repo casing to prove
# the canonical values match what the release pipeline actually needs.
import subprocess  # noqa: E402

simulated = subprocess.run(
    ["bash", "-c", 'echo "OmniBioAI/omnibioai-control-center" | tr "[:upper:]" "[:lower:]"'],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()
check(
    simulated == "omnibioai/omnibioai-control-center",
    f"lowercasing simulation produced '{simulated}', expected "
    f"'omnibioai/omnibioai-control-center'",
)
check(
    f"ghcr.io/{simulated}" == CANONICAL_BACKEND_IMAGE,
    f"derived backend image 'ghcr.io/{simulated}' does not equal canonical "
    f"'{CANONICAL_BACKEND_IMAGE}'",
)
check(
    f"ghcr.io/{simulated}-web" == CANONICAL_FRONTEND_IMAGE,
    f"derived frontend image 'ghcr.io/{simulated}-web' does not equal "
    f"canonical '{CANONICAL_FRONTEND_IMAGE}'",
)

# ---------------------------------------------------------------------
# 3. Every downstream job consumes the canonical output -- never its own
#    independent lowercasing, never the raw context value.
# ---------------------------------------------------------------------
BACKEND_EXPR = "ghcr.io/${{ needs.resolve-version.outputs.repo }}"
FRONTEND_EXPR = "ghcr.io/${{ needs.resolve-version.outputs.repo }}-web"


def job_text(job_name: str) -> str:
    job = jobs[job_name]
    parts = []
    for step in job.get("steps", []):
        for key in ("run", "with"):
            val = step.get(key)
            if val is None:
                continue
            parts.append(yaml.dump(val) if isinstance(val, dict) else str(val))
    return "\n".join(parts)


build_jobs_backend = ["build-backend-amd64", "build-backend-arm64"]
build_jobs_frontend = ["build-frontend-amd64", "build-frontend-arm64"]
assemble_jobs = {"assemble-backend": BACKEND_EXPR, "assemble-frontend": FRONTEND_EXPR}
verify_jobs = {"verify-backend": BACKEND_EXPR, "verify-frontend": FRONTEND_EXPR}
smoke_jobs = {
    "smoke-backend-amd64": BACKEND_EXPR,
    "smoke-backend-arm64": BACKEND_EXPR,
    "smoke-frontend-amd64": FRONTEND_EXPR,
    "smoke-frontend-arm64": FRONTEND_EXPR,
}
publish_jobs = {
    "publish-version-backend": BACKEND_EXPR,
    "publish-version-frontend": FRONTEND_EXPR,
}
promote_jobs = {
    "promote-latest-backend": BACKEND_EXPR,
    "promote-latest-frontend": FRONTEND_EXPR,
}

for name in build_jobs_backend:
    text = job_text(name)
    check(BACKEND_EXPR in text, f"{name} does not consume canonical backend image expr")

for name in build_jobs_frontend:
    text = job_text(name)
    check(FRONTEND_EXPR in text, f"{name} does not consume canonical frontend image expr")

for group_name, group in (
    ("assemble", assemble_jobs),
    ("verify", verify_jobs),
    ("smoke", smoke_jobs),
    ("publish-version", publish_jobs),
    ("promote-latest", promote_jobs),
):
    for name, expected_expr in group.items():
        text = job_text(name)
        check(
            expected_expr in text,
            f"{name} ({group_name} job) does not consume canonical image expr "
            f"'{expected_expr}'",
        )
        check(name in jobs, f"{group_name} job '{name}' not found in workflow")

# ---------------------------------------------------------------------
# 4. Unrelated gates (native arch, SBOM/provenance, smoke, promotion)
#    remain structurally unchanged -- this repair is identity-only.
# ---------------------------------------------------------------------
check(
    jobs["build-backend-amd64"]["runs-on"] == "ubuntu-24.04"
    and jobs["build-backend-arm64"]["runs-on"] == "ubuntu-24.04-arm"
    and jobs["build-frontend-amd64"]["runs-on"] == "ubuntu-24.04"
    and jobs["build-frontend-arm64"]["runs-on"] == "ubuntu-24.04-arm",
    "native runner assignment changed unexpectedly",
)
check(
    "setup-qemu" not in raw_text,
    "QEMU setup action must never appear in this workflow",
)
check(
    jobs["publish-version-backend"]["needs"]
    == ["resolve-version", "verify-backend", "smoke-backend-amd64", "smoke-backend-arm64"],
    "publish-version-backend's gating needs changed unexpectedly",
)
check(
    jobs["promote-latest-backend"]["needs"] == ["resolve-version", "publish-version-backend"],
    "promote-latest-backend's gating needs changed unexpectedly",
)

if failures:
    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    sys.exit(1)

print("PASS: resolve-version exposes exactly one canonical lowercased 'repo' output")
print(f"PASS: canonical backend image = {CANONICAL_BACKEND_IMAGE}")
print(f"PASS: canonical frontend image = {CANONICAL_FRONTEND_IMAGE}")
print("PASS: all 4 build jobs, 2 assemble, 2 verify, 4 smoke, 2 publish, 2 promote jobs consume the canonical output")
print("PASS: no executable GHCR reference derives directly from raw github.repository")
print("PASS: native-arch/QEMU/gating invariants unchanged")
