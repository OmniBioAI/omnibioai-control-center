from pathlib import Path


NGINX_CONFIG = Path(__file__).parents[1] / "docker/nginx/control-center.conf"


def _server_block_for(source: str, server_name: str) -> str:
    marker = f"server_name {server_name};"
    name_at = source.index(marker)
    start = source.rfind("server {", 0, name_at)
    depth = 0
    for position in range(start, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[start : position + 1]
    raise AssertionError(f"Unclosed server block for {server_name}")


def test_admin_standalone_server_sends_deny_framing_policy():
    source = NGINX_CONFIG.read_text()
    admin = _server_block_for(source, "admin.omnibioai.org")
    control = _server_block_for(source, "control.omnibioai.org")

    assert 'add_header Content-Security-Policy "frame-ancestors \'none\'" always;' in admin
    assert "frame-ancestors 'none'" not in control

