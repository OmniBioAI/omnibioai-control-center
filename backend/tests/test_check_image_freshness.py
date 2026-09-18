"""
tests/test_check_image_freshness.py

Unit tests for:
  - control_center.checks.image_freshness

Covers image-ref parsing (ghcr/dockerhub, namespaced/official images,
missing tag), the local container digest lookup, registry bearer-token
auth (ghcr uses a pull token, dockerhub anonymous), manifest/blob
fetching (registry-1.docker.io vs. the registry host directly), multi-
arch manifest platform selection, and _check_one()/get_image_freshness()'s
stale/not-stale classification with graceful degradation on any lookup
failure.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import image_freshness


class TestParseImageRef(unittest.TestCase):
    """_parse_image_ref()'s (registry, repo, tag) parsing across ghcr,
    official (library/), namespaced Docker Hub, and untagged images."""

    def test_ghcr_image_with_namespace(self) -> None:
        """A ghcr.io image ref parses into (host, namespace/repo, tag)."""
        result = image_freshness._parse_image_ref("ghcr.io/omnibioai/omnibioai-auth:latest")
        self.assertEqual(result, ("ghcr.io", "omnibioai/omnibioai-auth", "latest"))

    def test_official_image_gets_library_prefix(self) -> None:
        """An unqualified official image (e.g. "nginx") gets the
        implicit "library/" namespace and docker.io registry."""
        result = image_freshness._parse_image_ref("nginx:latest")
        self.assertEqual(result, ("docker.io", "library/nginx", "latest"))

    def test_namespaced_dockerhub_image(self) -> None:
        """A namespaced Docker Hub image (e.g. "prom/prometheus")
        resolves to docker.io without the "library/" prefix."""
        result = image_freshness._parse_image_ref("prom/prometheus:latest")
        self.assertEqual(result, ("docker.io", "prom/prometheus", "latest"))

    def test_missing_tag_defaults_to_latest(self) -> None:
        """An image ref with no ":tag" defaults to "latest"."""
        result = image_freshness._parse_image_ref("nginx")
        self.assertEqual(result, ("docker.io", "library/nginx", "latest"))


class TestLocalImageId(unittest.TestCase):
    """_local_image_id()'s docker-inspect-based digest lookup, failing
    safe to None on any error."""

    def test_returns_stripped_sha(self) -> None:
        """A successful docker inspect returns the digest with the
        "sha256:" prefix stripped."""
        result = MagicMock(returncode=0, stdout="sha256:abcdef123456\n")
        with patch.object(image_freshness.subprocess, "run", return_value=result):
            self.assertEqual(image_freshness._local_image_id("my-container"), "abcdef123456")

    def test_nonzero_returncode_returns_none(self) -> None:
        """A nonzero docker inspect exit code returns None."""
        result = MagicMock(returncode=1, stdout="")
        with patch.object(image_freshness.subprocess, "run", return_value=result):
            self.assertIsNone(image_freshness._local_image_id("my-container"))

    def test_empty_stdout_returns_none(self) -> None:
        """Empty stdout from a successful run still returns None."""
        result = MagicMock(returncode=0, stdout="")
        with patch.object(image_freshness.subprocess, "run", return_value=result):
            self.assertIsNone(image_freshness._local_image_id("my-container"))

    def test_exception_returns_none(self) -> None:
        """A subprocess exception (e.g. docker binary missing) returns
        None rather than propagating."""
        with patch.object(image_freshness.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertIsNone(image_freshness._local_image_id("my-container"))


class TestGetBearerToken(unittest.TestCase):
    """_get_bearer_token()'s registry-auth request, with ghcr using a
    configured pull token and Docker Hub going anonymous."""

    def test_returns_token(self) -> None:
        """A successful auth request returns the parsed token string."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"token": "abc123"}
        with patch("httpx.get", return_value=resp) as mock_get:
            token = image_freshness._get_bearer_token("ghcr.io", "omnibioai/foo")
        self.assertEqual(token, "abc123")
        mock_get.assert_called_once()

    def test_uses_pull_token_auth_for_ghcr(self) -> None:
        """A configured GHCR_PULL_TOKEN is sent as HTTP basic auth
        ("token", <secret>) for a ghcr.io request."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"token": "abc123"}
        with patch.object(image_freshness, "GHCR_PULL_TOKEN", "secret-token"):
            with patch("httpx.get", return_value=resp) as mock_get:
                image_freshness._get_bearer_token("ghcr.io", "omnibioai/foo")
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["auth"], ("token", "secret-token"))

    def test_no_auth_for_dockerhub(self) -> None:
        """A docker.io request sends no HTTP auth (anonymous pull)."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"token": "xyz"}
        with patch("httpx.get", return_value=resp) as mock_get:
            image_freshness._get_bearer_token("docker.io", "library/nginx")
        _, kwargs = mock_get.call_args
        self.assertIsNone(kwargs["auth"])


class TestFetchManifestAndBlob(unittest.TestCase):
    """_fetch_manifest()/_fetch_blob()'s registry-specific request URLs
    and JSON parsing."""

    def test_fetch_manifest_returns_json(self) -> None:
        """A docker.io manifest fetch requests registry-1.docker.io
        (Docker Hub's real registry host, not "docker.io" itself) and
        returns the parsed body."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"config": {"digest": "sha256:abc"}}
        with patch("httpx.get", return_value=resp) as mock_get:
            result = image_freshness._fetch_manifest("docker.io", "library/nginx", "latest", "tok")
        self.assertEqual(result, {"config": {"digest": "sha256:abc"}})
        args, kwargs = mock_get.call_args
        self.assertIn("registry-1.docker.io", args[0])

    def test_fetch_manifest_ghcr_uses_registry_host_directly(self) -> None:
        """A ghcr.io manifest fetch requests ghcr.io directly (no
        registry-host substitution, unlike Docker Hub)."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {}
        with patch("httpx.get", return_value=resp) as mock_get:
            image_freshness._fetch_manifest("ghcr.io", "omnibioai/foo", "latest", "tok")
        args, _ = mock_get.call_args
        self.assertIn("ghcr.io", args[0])

    def test_fetch_blob_returns_json(self) -> None:
        """_fetch_blob() returns the parsed JSON blob body."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"created": "2026-01-01T00:00:00Z"}
        with patch("httpx.get", return_value=resp):
            result = image_freshness._fetch_blob("ghcr.io", "omnibioai/foo", "sha256:abc", "tok")
        self.assertEqual(result["created"], "2026-01-01T00:00:00Z")


class TestRemoteConfigInfo(unittest.TestCase):
    """_remote_config_info()'s (digest, created) lookup, including
    multi-arch manifest-index platform selection and graceful
    degradation on any lookup failure."""

    def test_single_arch_manifest(self) -> None:
        """A plain (non-index) manifest's config digest/created
        timestamp are returned directly."""
        with patch.object(image_freshness, "_get_bearer_token", return_value="tok"):
            with patch.object(image_freshness, "_fetch_manifest",
                               return_value={"config": {"digest": "sha256:abc123"}}):
                with patch.object(image_freshness, "_fetch_blob",
                                   return_value={"created": "2026-01-01T00:00:00Z"}):
                    digest, created = image_freshness._remote_config_info("ghcr.io", "omnibioai/foo", "latest")
        self.assertEqual(digest, "abc123")
        self.assertEqual(created, "2026-01-01T00:00:00Z")

    def test_multi_arch_manifest_selects_matching_platform(self) -> None:
        """A multi-arch manifest index resolves to the sub-manifest
        matching the local architecture (arm64 here), not the first entry."""
        index = {
            "manifests": [
                {"platform": {"os": "linux", "architecture": "amd64"}, "digest": "sha256:amd"},
                {"platform": {"os": "linux", "architecture": "arm64"}, "digest": "sha256:arm"},
            ],
        }
        sub_manifest = {"config": {"digest": "sha256:def456"}}

        with patch.object(image_freshness, "_LOCAL_ARCH", "arm64"):
            with patch.object(image_freshness, "_get_bearer_token", return_value="tok"):
                with patch.object(image_freshness, "_fetch_manifest",
                                   side_effect=[index, sub_manifest]):
                    with patch.object(image_freshness, "_fetch_blob", return_value={"created": "ts"}):
                        digest, created = image_freshness._remote_config_info(
                            "ghcr.io", "omnibioai/foo", "latest")
        self.assertEqual(digest, "def456")
        self.assertEqual(created, "ts")

    def test_multi_arch_no_matching_platform_returns_none(self) -> None:
        """A manifest index with no entry matching the local platform
        returns (None, None) rather than raising or picking the wrong one."""
        index = {"manifests": [{"platform": {"os": "windows", "architecture": "amd64"}, "digest": "sha256:x"}]}
        with patch.object(image_freshness, "_get_bearer_token", return_value="tok"):
            with patch.object(image_freshness, "_fetch_manifest", return_value=index):
                digest, created = image_freshness._remote_config_info("ghcr.io", "omnibioai/foo", "latest")
        self.assertIsNone(digest)
        self.assertIsNone(created)

    def test_missing_config_digest_returns_none(self) -> None:
        """A manifest with no "config" key at all returns (None, None)."""
        with patch.object(image_freshness, "_get_bearer_token", return_value="tok"):
            with patch.object(image_freshness, "_fetch_manifest", return_value={}):
                digest, created = image_freshness._remote_config_info("ghcr.io", "omnibioai/foo", "latest")
        self.assertIsNone(digest)
        self.assertIsNone(created)

    def test_blob_fetch_failure_still_returns_digest(self) -> None:
        """A failure fetching the config blob (for the created
        timestamp) still returns the already-known digest, with
        created=None rather than failing the whole lookup."""
        with patch.object(image_freshness, "_get_bearer_token", return_value="tok"):
            with patch.object(image_freshness, "_fetch_manifest",
                               return_value={"config": {"digest": "sha256:abc123"}}):
                with patch.object(image_freshness, "_fetch_blob", side_effect=RuntimeError("boom")):
                    digest, created = image_freshness._remote_config_info("ghcr.io", "omnibioai/foo", "latest")
        self.assertEqual(digest, "abc123")
        self.assertIsNone(created)


class TestCheckOne(unittest.TestCase):
    """_check_one()'s per-container stale/not-stale determination by
    comparing the local image digest against the remote registry."""

    def test_no_local_container_returns_none(self) -> None:
        """A container with no running local image at all returns None
        (excluded, not reported as an error)."""
        with patch.object(image_freshness, "_local_image_id", return_value=None):
            result = image_freshness._check_one(("svc", "container", "img:latest"))
        self.assertIsNone(result)

    def test_matching_digest_is_not_stale(self) -> None:
        """A local digest matching the remote digest is stale=False,
        with last_pushed reported."""
        with patch.object(image_freshness, "_local_image_id", return_value="abc123"):
            with patch.object(image_freshness, "_remote_config_info", return_value=("abc123", "ts")):
                result = image_freshness._check_one(("svc", "container", "img:latest"))
        self.assertFalse(result["stale"])
        self.assertEqual(result["last_pushed"], "ts")

    def test_mismatched_digest_is_stale(self) -> None:
        """A local digest differing from the remote digest is stale=True."""
        with patch.object(image_freshness, "_local_image_id", return_value="abc123"):
            with patch.object(image_freshness, "_remote_config_info", return_value=("def456", "ts")):
                result = image_freshness._check_one(("svc", "container", "img:latest"))
        self.assertTrue(result["stale"])

    def test_remote_lookup_failure_not_flagged_stale(self) -> None:
        """A remote lookup failure (e.g. network down) is reported
        stale=False with last_pushed="unknown", not a fabricated stale
        flag or an unhandled exception."""
        with patch.object(image_freshness, "_local_image_id", return_value="abc123"):
            with patch.object(image_freshness, "_remote_config_info", side_effect=RuntimeError("network down")):
                result = image_freshness._check_one(("svc", "container", "img:latest"))
        self.assertFalse(result["stale"])
        self.assertEqual(result["last_pushed"], "unknown")


class TestGetImageFreshness(unittest.TestCase):
    """get_image_freshness()'s aggregation of _check_one() across every
    configured image."""

    def test_filters_out_none_results(self) -> None:
        """A service with no local container (_check_one returns None)
        is excluded from the final images list entirely."""
        def fake_check_one(entry):
            return None if entry[0] == "toolserver" else {"service": entry[0], "stale": False}

        with patch.object(image_freshness, "_check_one", side_effect=fake_check_one):
            result = image_freshness.get_image_freshness()

        services = {img["service"] for img in result["images"]}
        self.assertNotIn("toolserver", services)
        self.assertEqual(len(result["images"]), len(image_freshness._IMAGES) - 1)


if __name__ == "__main__":
    unittest.main()
