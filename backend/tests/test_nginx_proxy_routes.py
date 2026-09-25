"""
tests/test_nginx_proxy_routes.py
Regression guard for docker/nginx/api-proxy.conf.

nginx forwards only the paths listed in api-proxy.conf to the backend;
anything else falls through to `location /` and gets the SPA's
index.html back with HTTP 200. GET /showcase and GET /uptime shipped
without entries and did exactly that on control.omnibioai.org. This test
reads every path the public dashboard's data module requests
(frontend/cc-ui/src/publicOverview.ts) plus the other anonymous calls the
public build makes, and fails if nginx would not forward one of them.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROXY_CONF = REPO / "docker" / "nginx" / "api-proxy.conf"
PUBLIC_DATA_MODULE = REPO / "frontend" / "cc-ui" / "src" / "publicOverview.ts"

# Anonymous calls the public build makes outside publicOverview.ts
# (api.ts fetchHealth/fetchReportData/fetchReportStatus, LlmPage, CloudPage,
# integrations.ts).
OTHER_PUBLIC_PATHS = ["/health", "/report/data", "/report/status", "/llms", "/cloud", "/integrations"]


def _locations() -> list[tuple[str, str]]:
    """(modifier, path) for every proxied location; modifier is '=' for an
    exact match, '' or '^~' for a prefix match."""
    text = PROXY_CONF.read_text(encoding="utf-8")
    found = []
    for match in re.finditer(r"^location\s+(=|\^~)?\s*(/[^\s{]*)\s*\{(?P<body>[^}]*)", text, re.M):
        if "proxy_pass" in match["body"]:
            found.append((match[1] or "", match[2]))
    return found


def _proxied(path: str, locations: list[tuple[str, str]]) -> bool:
    for modifier, loc in locations:
        if modifier == "=" and path == loc:
            return True
        if modifier != "=" and path.startswith(loc):
            return True
    return False


def _public_data_paths() -> list[str]:
    source = PUBLIC_DATA_MODULE.read_text(encoding="utf-8")
    return re.findall(r"getJson<[^>]*>\('(/[^']*)'\)", source)


class TestPublicRoutesAreProxied(unittest.TestCase):
    def test_public_data_module_paths_found(self) -> None:
        """Sanity check that the extraction still sees the module's calls."""
        paths = _public_data_paths()
        self.assertIn("/showcase", paths)
        self.assertIn("/uptime", paths)

    def test_every_public_path_is_proxied(self) -> None:
        locations = _locations()
        missing = [p for p in _public_data_paths() + OTHER_PUBLIC_PATHS if not _proxied(p, locations)]
        self.assertEqual(missing, [], f"add a `location` for these to {PROXY_CONF.name}")

    def test_matcher_semantics(self) -> None:
        locations = [("=", "/exact"), ("", "/prefix"), ("^~", "/caret/")]
        self.assertTrue(_proxied("/exact", locations))
        self.assertFalse(_proxied("/exact/more", locations))
        self.assertTrue(_proxied("/prefix/sub", locations))
        self.assertTrue(_proxied("/caret/x", locations))
        self.assertFalse(_proxied("/other", locations))


if __name__ == "__main__":
    unittest.main()
