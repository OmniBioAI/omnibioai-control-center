"""Report CLI authentication: no live IAM credentials or network required."""

import importlib
import io
import json
import os
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


@pytest.fixture
def login(report, monkeypatch):
    module = importlib.import_module("shared.operator_login")
    monkeypatch.delenv("CONTROL_CENTER_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("IAM_URL", "http://127.0.0.1:8001")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    return module


def test_environment_token_skips_all_login_work(login, monkeypatch):
    monkeypatch.setenv("CONTROL_CENTER_ACCESS_TOKEN", "existing-token")
    with patch.object(login, "login_operator") as authenticate, \
            patch.object(login, "_verify_infra_access") as verify:
        with login.operator_session("http://127.0.0.1:7070"):
            assert login._admin_header()["Authorization"] == "Bearer existing-token"
        authenticate.assert_not_called()
        verify.assert_not_called()


@pytest.mark.parametrize("mfa", [False, True])
def test_interactive_login_contracts_and_memory_only(login, monkeypatch, tmp_path, capsys, mfa):
    password, token, refresh, challenge, code = (
        "private-password", "private-access", "private-refresh", "private-challenge", "private-code",
    )
    monkeypatch.chdir(tmp_path)
    replies = [{"access_token": token, "refresh_token": refresh}]
    if mfa:
        replies.insert(0, {"mfa_required": True, "challenge_token": challenge, "methods": ["totp"]})
    replies.append({"seats_used": 1})  # protected server authorization check
    with patch("builtins.input", return_value="operator@example.test") as email, \
            patch.object(login.getpass, "getpass", side_effect=[password, code]) as secret, \
            patch.object(login, "_request_json", side_effect=replies) as request:
        with login.operator_session("http://127.0.0.1:7070"):
            assert login._admin_header()["Authorization"] == f"Bearer {token}"
            assert "CONTROL_CENTER_ACCESS_TOKEN" not in os.environ
            authenticated_output = capsys.readouterr()
            assert "✓ Authenticated" in authenticated_output.out
        email.assert_called_once_with("Email: ")
        assert secret.call_args_list[0].args == ("Password: ",)
        assert request.call_args_list[0].args == (
            "http://127.0.0.1:8001/auth/login", {"email": "operator@example.test", "password": password},
        )
        if mfa:
            assert secret.call_args_list[1].args == ("MFA code: ",)
            assert request.call_args_list[1].args == (
                "http://127.0.0.1:8001/users/me/mfa/challenge", {"challenge_token": challenge, "code": code},
            )
        assert request.call_args_list[-1].kwargs == {"headers": {"Authorization": f"Bearer {token}"}}
    assert login.operator_access_token.get() == ""
    assert not list(tmp_path.iterdir())
    captured = capsys.readouterr()
    for value in (password, token, refresh, challenge, code):
        assert value not in authenticated_output.out + authenticated_output.err + captured.out + captured.err


@pytest.mark.parametrize("status, mfa, message", [
    (401, False, "Invalid IAM operator credentials"),
    (401, True, "MFA verification failed"),
    (400, True, "MFA verification failed"),
    (403, False, "SSO or MFA enrollment"),
    (429, False, "rate limited"),
    (503, False, "IAM unavailable"),
])
def test_iam_error_messages_do_not_leak(login, capsys, status, mfa, message):
    secret = "private-credential-and-token"
    error = urllib.error.HTTPError(secret, status, secret, {}, io.BytesIO(secret.encode()))
    with patch.object(login, "_request_json", side_effect=error):
        with pytest.raises(login.ReportAuthenticationError, match=message) as caught:
            login._post_auth("http://127.0.0.1:8001/auth/login", {"password": secret}, mfa=mfa)
    captured = capsys.readouterr()
    assert secret not in str(caught.value) + captured.out + captured.err


def test_iam_unavailable(login):
    with patch.object(login, "_request_json", side_effect=urllib.error.URLError("private-secret")):
        with pytest.raises(login.ReportAuthenticationError, match="IAM unavailable") as caught:
            login._post_auth("http://127.0.0.1:8001/auth/login", {})
    assert "private-secret" not in str(caught.value)


@pytest.mark.parametrize("status, message", [(401, "authentication failure"), (403, "lacks platform.manage_infra")])
def test_authorization_failure_stops_before_generation(login, report, monkeypatch, tmp_path, capsys, status, message):
    monkeypatch.setattr(sys, "argv", ["generate_report.py"])
    token = "private-access"
    error = urllib.error.HTTPError(token, status, token, {}, io.BytesIO(token.encode()))
    with patch.object(login, "login_operator", return_value=token), \
            patch.object(login, "_request_json", side_effect=error), \
            patch.object(report, "generate_report") as generate:
        assert report.main() == 1
        generate.assert_not_called()
    assert login.operator_access_token.get() == ""
    captured = capsys.readouterr()
    assert message in captured.err
    assert token not in captured.out + captured.err
    assert "✓ Authenticated" not in captured.out


def test_missing_token_cli_invokes_interactive_login(login, report, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["generate_report.py"])
    with patch.object(login, "login_operator", return_value="private-access") as authenticate, \
            patch.object(login, "_verify_infra_access"), \
            patch.object(report, "generate_report", return_value=tmp_path / "report.html") as generate:
        assert report.main() == 0
    authenticate.assert_called_once()
    generate.assert_called_once()
    captured = capsys.readouterr()
    assert "private-access" not in captured.out + captured.err
    assert login.operator_access_token.get() == ""


def test_getpass_echo_fallback_is_rejected(login):
    import getpass
    import warnings

    def fallback(prompt):
        warnings.warn("unable to disable echo", getpass.GetPassWarning)
        pytest.fail("getpass fallback must stop before echoing input")

    with patch("builtins.input", return_value="operator@example.test"), \
            patch.object(login.getpass, "getpass", side_effect=fallback):
        with pytest.raises(login.ReportAuthenticationError, match="secure terminal input unavailable"):
            login.login_operator()


def test_public_health_without_token_remains_functional(report, monkeypatch):
    from shared.health_fetch import fetch_health

    monkeypatch.delenv("CONTROL_CENTER_ACCESS_TOKEN", raising=False)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"overall_status":"UP"}'
    with patch("urllib.request.urlopen", return_value=response) as open_url:
        assert fetch_health("http://127.0.0.1:7070").overall_status == "UP"
    assert open_url.call_args.args[0].get_header("Authorization") is None


def test_portable_compose_path(report, monkeypatch):
    monkeypatch.delenv("OMNIBIOAI_COMPOSE_PATH", raising=False)
    with patch.object(Path, "exists", return_value=False):
        assert report._default_compose_path() == Path(report.__file__).resolve().parents[2] / "omnibioai-studio/docker-compose.yml"


def test_iam_url_uses_existing_configuration(login, monkeypatch, tmp_path):
    monkeypatch.delenv("IAM_URL", raising=False)
    config = tmp_path / "control_center.yaml"
    config.write_text('services:\n  auth-service:\n    url: https://iam.example.test/health\n')
    monkeypatch.setenv("CONTROL_CENTER_CONFIG", str(config))
    assert login.iam_url() == "https://iam.example.test"
    monkeypatch.setenv("IAM_URL", "https://override.example.test")
    assert login.iam_url() == "https://override.example.test"


@pytest.mark.parametrize("url", ["http://remote.example.test", "https://user:secret@example.test", "https://example.test?token=secret"])
def test_unsafe_credential_destination_rejected_before_prompt(login, monkeypatch, url):
    monkeypatch.setenv("IAM_URL", url)
    with patch("builtins.input") as prompt:
        with pytest.raises(login.ReportAuthenticationError, match="trusted HTTPS"):
            login.login_operator()
        prompt.assert_not_called()


def test_interactive_token_used_in_license_html_without_leaks(login, tmp_path, capsys):
    from sections.misc.license import license_section_html

    token, password = "private-access", "private-password"
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"seats_used":1,"seats_total":2,"licenses":[]}'
    with patch("builtins.input", return_value="operator@example.test"), \
            patch.object(login.getpass, "getpass", return_value=password), \
            patch.object(login, "_request_json", side_effect=[{"access_token": token}, {}]), \
            patch("urllib.request.urlopen", return_value=response) as request:
        with login.operator_session("http://127.0.0.1:7070"):
            html = license_section_html("http://127.0.0.1:7070")
    assert request.call_args.args[0].get_header("Authorization") == f"Bearer {token}"
    assert "1/2" in html
    captured = capsys.readouterr()
    for secret in (token, password):
        assert secret not in html + captured.out + captured.err
    assert not list(tmp_path.iterdir())


def test_json_transport_uses_schema_and_no_cookie_jar(login):
    payload = {"email": "operator@example.test", "password": "private-password"}
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"access_token":"private-access"}'
    opener = MagicMock()
    opener.open.return_value = response
    with patch.object(login.urllib.request, "build_opener", return_value=opener) as build:
        result = login._request_json("http://127.0.0.1:8001/auth/login", payload)
    request = opener.open.call_args.args[0]
    assert request.get_method() == "POST"
    assert json.loads(request.data) == payload
    assert request.get_header("Cookie") is None
    assert request.full_url == "http://127.0.0.1:8001/auth/login"
    assert not any(isinstance(handler, login.urllib.request.HTTPCookieProcessor) for handler in build.call_args.args)
    assert result["access_token"] == "private-access"
    assert login._NoRedirect().redirect_request(request, None, 307, "redirect", {}, "https://other.example.test") is None


@pytest.mark.parametrize("reply, message", [
    ({"mfa_required": True}, "invalid MFA challenge"),
    ({"refresh_token": "private-refresh"}, "no user access token"),
    ({"access_token": None}, "no user access token"),
])
def test_invalid_login_responses_fail_closed(login, reply, message):
    with patch("builtins.input", return_value="operator@example.test"), \
            patch.object(login.getpass, "getpass", return_value="private-password"), \
            patch.object(login, "_request_json", return_value=reply):
        with pytest.raises(login.ReportAuthenticationError, match=message):
            login.login_operator()


def test_interactive_token_cleared_after_generation_failure(login):
    with patch.object(login, "login_operator", return_value="private-access"), \
            patch.object(login, "_verify_infra_access"):
        with pytest.raises(RuntimeError, match="report failure"):
            with login.operator_session("http://127.0.0.1:7070"):
                raise RuntimeError("report failure")
    assert login.operator_access_token.get() == ""


def test_noninteractive_missing_token_never_prompts(login, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with patch.object(login, "login_operator") as authenticate:
        with pytest.raises(login.ReportAuthenticationError, match="non-interactive"):
            with login.operator_session("http://127.0.0.1:7070"):
                pytest.fail("must not start report")
        authenticate.assert_not_called()
