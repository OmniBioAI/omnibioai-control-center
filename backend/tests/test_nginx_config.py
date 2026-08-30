"""
tests/test_nginx_config.py

Regression coverage for the Admin Console login outage root-caused during
the browser-login diagnosis: docker/nginx/api-proxy.conf used a bare
`proxy_pass http://control-center:7070;` in every location. nginx resolves
a bare proxy_pass hostname exactly once, when the worker process starts --
not on Docker's DNS TTL -- so any time the control-center container was
recreated (redeploy, crash-loop restart) *after* control-center-web's nginx
had already started, every proxied route (including /auth/login) kept
sending traffic to the old, now-dead IP and 502'd with "connection
refused", even though auth-service itself was healthy the whole time.
Confirmed live in this container's own access/error logs before the fix.

The fix (matching the pattern already used for billing-service in the
sibling omnibioai-studio/docker/nginx-router.conf) is a `resolver` +
request-time `$control_center_upstream` variable, declared once per server
block in control-center.conf and referenced by every location in
api-proxy.conf, so the upstream IP is re-resolved (capped at 10s) instead
of cached for the nginx process's lifetime.

These are static config assertions, not a running-nginx integration test
(no nginx binary/container dependency in this test suite) -- they exist so
a future edit can't silently reintroduce a bare, cache-forever
`proxy_pass http://control-center:7070;` without a test failing.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

NGINX_DIR = Path(__file__).resolve().parents[2] / "docker" / "nginx"


class TestNginxApiProxyConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.api_proxy_conf = self._strip_comment_lines(NGINX_DIR / "api-proxy.conf")
        self.control_center_conf = self._strip_comment_lines(NGINX_DIR / "control-center.conf")

    @staticmethod
    def _strip_comment_lines(path: Path) -> str:
        # Drop full-line `#` comments before matching -- this module's own
        # header comment quotes the literal bad pattern
        # ("proxy_pass http://control-center:7070;") as documentation of
        # what NOT to do, which would otherwise false-positive the checks
        # below.
        return "\n".join(
            line for line in path.read_text().splitlines() if not line.strip().startswith("#")
        )

    def test_no_bare_control_center_hostname_in_proxy_pass(self) -> None:
        # The exact regression: a static hostname in proxy_pass is resolved
        # once at worker-start and never refreshed. Every proxy_pass in this
        # file must go through the $control_center_upstream variable instead.
        bare_hostname_proxy_pass = re.findall(
            r"proxy_pass\s+http://control-center:7070", self.api_proxy_conf,
        )
        self.assertEqual(
            bare_hostname_proxy_pass, [],
            "found a bare 'proxy_pass http://control-center:7070' -- this "
            "caches the resolved IP for the nginx worker's lifetime and "
            "502s every route (including /auth/login) after control-center "
            "is ever recreated independently of control-center-web. Use "
            "'proxy_pass http://$control_center_upstream;' instead.",
        )

    def test_every_proxy_pass_uses_the_resolved_upstream_variable(self) -> None:
        proxy_pass_targets = re.findall(r"proxy_pass\s+(\S+);", self.api_proxy_conf)
        self.assertTrue(proxy_pass_targets, "expected at least one proxy_pass in api-proxy.conf")
        for target in proxy_pass_targets:
            self.assertEqual(
                target, "http://$control_center_upstream",
                f"proxy_pass target {target!r} bypasses the request-time DNS "
                "resolution -- see test_no_bare_control_center_hostname_in_proxy_pass",
            )

    def test_both_server_blocks_declare_resolver_and_upstream_variable(self) -> None:
        # api-proxy.conf's $control_center_upstream is only ever request-time
        # re-resolved if the server block that includes it also declares a
        # `resolver` -- without one, nginx treats the variable's value as just
        # another static hostname and the same staleness bug comes back.
        server_blocks = re.findall(r"server\s*\{.*?\n\}", self.control_center_conf, re.DOTALL)
        self.assertEqual(len(server_blocks), 2, "expected exactly the control + admin server blocks")
        for block in server_blocks:
            self.assertRegex(
                block, r"resolver\s+127\.0\.0\.11\s+valid=10s;",
                "server block is missing the Docker embedded-DNS resolver "
                "directive needed for $control_center_upstream to actually "
                "re-resolve per request",
            )
            self.assertRegex(
                block, r"set\s+\$control_center_upstream\s+control-center:7070;",
                "server block is missing the $control_center_upstream assignment "
                "that api-proxy.conf's locations proxy_pass to",
            )

    def test_regression_health_api_is_separate_from_spa_route(self) -> None:
        self.assertRegex(
            self.api_proxy_conf,
            r"location\s+=\s+/regression-health/data\s*\{[\s\S]*?"
            r"rewrite\s+\^/regression-health/data\$\s+/regression-health\s+break;[\s\S]*?"
            r"proxy_pass\s+http://\$control_center_upstream;",
        )
        self.assertNotRegex(
            self.api_proxy_conf,
            r"location\s+(?:=\s+)?/regression-health\s*\{",
            "the SPA route must not be claimed by an API proxy location",
        )

    def test_deployment_health_api_is_separate_from_spa_route(self) -> None:
        # DH-3: same REG-010 route-collision check, for Deployment Health's
        # own SPA (/deployment-health) vs. API (/deployment-health/data)
        # split.
        self.assertRegex(
            self.api_proxy_conf,
            r"location\s+=\s+/deployment-health/data\s*\{[\s\S]*?"
            r"rewrite\s+\^/deployment-health/data\$\s+/deployment-health\s+break;[\s\S]*?"
            r"proxy_pass\s+http://\$control_center_upstream;",
        )
        self.assertNotRegex(
            self.api_proxy_conf,
            r"location\s+(?:=\s+)?/deployment-health\s*\{",
            "the SPA route must not be claimed by an API proxy location",
        )

    def test_security_posture_api_is_separate_from_spa_route(self) -> None:
        self.assertRegex(
            self.api_proxy_conf,
            r"location\s+=\s+/security-posture/data\s*\{[\s\S]*?"
            r"rewrite\s+\^/security-posture/data\$\s+/security-posture\s+break;[\s\S]*?"
            r"proxy_pass\s+http://\$control_center_upstream;",
        )
        self.assertNotRegex(
            self.api_proxy_conf,
            r"location\s+(?:=\s+)?/security-posture\s*\{",
            "the SPA route must not be claimed by an API proxy location",
        )


if __name__ == "__main__":
    unittest.main()
