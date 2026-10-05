"""Report CLI authentication: no live IAM credentials or network required."""

import importlib
import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def report(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("generate_report")


@pytest.mark.parametrize("token", [None, "", "   "])
@pytest.mark.parametrize("skip_health", [False, True])
def test_missing_token_precedes_expensive_work(report, monkeypatch, tmp_path, token, skip_health):
    from shared.health_fetch import ReportAuthenticationError

    if token is None:
        monkeypatch.delenv("CONTROL_CENTER_ACCESS_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CONTROL_CENTER_ACCESS_TOKEN", token)
    with patch.object(report, "ensure_cloc") as cloc, \
            patch.object(report, "collect_coverage") as coverage, \
            patch.object(report, "fetch_health") as health, \
            patch.object(report, "build_report") as build:
        with pytest.raises(ReportAuthenticationError, match="CONTROL_CENTER_ACCESS_TOKEN is required"):
            report.generate_report(tmp_path, skip_health=skip_health)
        for operation in (cloc, coverage, health, build):
            operation.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_missing_token_cli_error(report, monkeypatch, capsys):
    monkeypatch.delenv("CONTROL_CENTER_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["generate_report.py"])
    assert report.main() == 1
    captured = capsys.readouterr()
    assert "CONTROL_CENTER_ACCESS_TOKEN is required" in captured.err
    assert "short-lived IAM-issued operator access token" in captured.err
    assert "platform.manage_infra" in captured.err
    assert "Running cloc" not in captured.out


def test_license_forwards_token_and_renders_success(report, monkeypatch, capsys):
    from sections.misc.license import license_section_html

    token = "test-only-secret-do-not-display"
    monkeypatch.setenv("CONTROL_CENTER_ACCESS_TOKEN", token)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({
        "seats_used": 1, "seats_total": 2, "licenses": [],
    }).encode()
    with patch("urllib.request.urlopen", return_value=response) as open_url:
        html = license_section_html("http://127.0.0.1:7070")
    request = open_url.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:7070/license"
    assert request.get_header("Authorization") == f"Bearer {token}"
    assert "1/2" in html
    captured = capsys.readouterr()
    assert token not in captured.out + captured.err + html


@pytest.mark.parametrize("status, classification", [
    (401, "authentication failure"), (403, "insufficient permission"),
])
def test_authentication_http_failure_reaches_cli_without_leak(
    report, monkeypatch, capsys, status, classification,
):
    from sections.misc.license import license_section_html

    token = "test-only-secret-do-not-display"
    monkeypatch.setenv("CONTROL_CENTER_ACCESS_TOKEN", token)
    monkeypatch.setattr(sys, "argv", ["generate_report.py"])
    error = urllib.error.HTTPError(
        f"http://example.invalid/{token}", status, token, {}, io.BytesIO(token.encode()),
    )
    with patch.object(report, "generate_report", side_effect=lambda **kwargs: license_section_html(
        kwargs["control_center_url"]
    )), patch("urllib.request.urlopen", side_effect=error):
        assert report.main() == 1
    captured = capsys.readouterr()
    assert f"HTTP {status} {classification}" in captured.err
    assert "CONTROL_CENTER_ACCESS_TOKEN" in captured.err
    assert token not in captured.out + captured.err
    assert "not implemented" not in captured.out + captured.err


@pytest.mark.parametrize("status", [404, 501, 503])
def test_unavailable_endpoint_is_separate_from_authentication(report, monkeypatch, capsys, status):
    from sections.misc.license import license_section_html

    token = "test-only-secret-do-not-display"
    monkeypatch.setenv("CONTROL_CENTER_ACCESS_TOKEN", token)
    error = urllib.error.HTTPError(token, status, token, {}, io.BytesIO(token.encode()))
    with patch("urllib.request.urlopen", side_effect=error):
        html = license_section_html("http://127.0.0.1:7070")
    captured = capsys.readouterr()
    assert f"HTTP {status}" in html
    assert "endpoint unavailable" in html
    assert "authentication failure" not in html
    assert token not in captured.out + captured.err + html


def test_connection_failure_does_not_leak_exception_details(report, monkeypatch, capsys):
    from sections.misc.license import license_section_html

    token = "test-only-secret-do-not-display"
    monkeypatch.setenv("CONTROL_CENTER_ACCESS_TOKEN", token)
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(token)):
        html = license_section_html("http://127.0.0.1:7070")
    captured = capsys.readouterr()
    assert "connection failed or timed out" in html
    assert token not in captured.out + captured.err + html


def test_present_token_preserves_generation_flow(report, monkeypatch, tmp_path, capsys):
    token = "test-only-secret-do-not-display"
    monkeypatch.setenv("CONTROL_CENTER_ACCESS_TOKEN", token)
    health = report.EcosystemHealth(overall_status="UP", generated_at="")
    with patch.object(report, "ensure_cloc"), \
            patch.object(report, "_resolve_target_paths", return_value=[]), \
            patch.object(report, "fetch_health", return_value=health) as fetch, \
            patch.object(report, "build_report") as build:
        result = report.generate_report(tmp_path, skip_coverage=True)
    fetch.assert_called_once()
    build.assert_called_once()
    assert build.call_args.kwargs["health"] is health
    assert result == tmp_path / report.DEFAULT_OUT_PATH
    captured = capsys.readouterr()
    assert token not in captured.out + captured.err
