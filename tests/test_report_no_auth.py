from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "sections" / "misc" / "license.py"
SPEC = importlib.util.spec_from_file_location("report_license_section", MODULE_PATH)
assert SPEC is not None
report_license_section = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(report_license_section)


def test_license_section_skips_protected_fetch_without_token(monkeypatch) -> None:
    monkeypatch.setattr(report_license_section, "_admin_header", lambda: {})

    def unexpected_urlopen(*args, **kwargs):
        raise AssertionError("protected /license endpoint must not be contacted")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_urlopen)

    html = report_license_section.license_section_html("http://127.0.0.1:7070")

    assert "Protected license data skipped" in html
    assert "CONTROL_CENTER_ACCESS_TOKEN" in html
