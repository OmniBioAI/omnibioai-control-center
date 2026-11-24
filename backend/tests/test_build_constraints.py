"""The Control Center image installs exact third-party versions (backend/constraints.txt).

2026-11-24: a rebuild resolved backend/pyproject.toml's open ranges to sentry-sdk 3.0.0,
which rejects send_default_pii, so control_center.main failed at import. The Dockerfile now
installs with `pip install -c constraints.txt .` (versions taken from the production image);
upgrades are deliberate edits of constraints.txt.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
OWN = {"omnibioai-control-center"}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _constraints() -> dict[str, str]:
    pins = {}
    for line in (BACKEND / "constraints.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, version = line.partition("==")
        assert sep and version and " " not in line, f"constraints.txt: not an exact pin: {line!r}"
        pins[_norm(name)] = version
    return pins


def test_dockerfile_installs_with_the_constraints():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "COPY backend/constraints.txt ." in dockerfile
    installs = [ln for ln in dockerfile.splitlines()
                if re.search(r"\bpip3? install\b", ln) and not ln.lstrip().startswith("#")]
    assert installs and all("-c constraints.txt" in ln for ln in installs), installs


def test_constraints_are_exact_pins_without_urls_or_the_package_itself():
    text = (BACKEND / "constraints.txt").read_text()
    assert "://" not in text and " @ " not in text
    assert not set(_constraints()) & OWN


def test_every_declared_dependency_is_pinned():
    deps = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"]["dependencies"]
    names = {_norm(re.split(r"[\s\[<>=!~;@]", d, maxsplit=1)[0]) for d in deps}
    missing = sorted(names - OWN - set(_constraints()))
    assert not missing, f"declared in backend/pyproject.toml but not pinned in constraints.txt: {missing}"


def test_sentry_sdk_stays_below_3():
    assert int(_constraints()["sentry-sdk"].split(".")[0]) < 3
    assert "sentry-sdk[fastapi,starlette]>=2.0.0,<3" in (BACKEND / "pyproject.toml").read_text()
