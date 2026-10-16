"""The Garmin MCP URL: no bearer token in clear outside the loopback and private networks."""

import socket

import pytest

from lifter.config import ConfigError
from lifter.garmin import McpToolCaller, McpUnavailable, check_mcp_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/mcp",
        "http://localhost:8080/mcp",
        "http://[::1]:8080/mcp",
        "http://192.168.1.20:8080/mcp",
        "http://10.0.0.5/mcp",
        "http://100.101.102.103:8080/mcp",  # Tailscale
        "https://garmin.example.com/mcp",
    ],
)
def test_accepted_urls(url):
    check_mcp_url(url)


@pytest.mark.parametrize(
    "url",
    ["http://8.8.8.8/mcp", "ftp://127.0.0.1/mcp", "127.0.0.1:8080/mcp", "http:///mcp", ""],
)
def test_refused_urls(url):
    with pytest.raises(ConfigError, match="GARMIN_MCP_URL"):
        check_mcp_url(url)


def test_a_name_is_judged_by_every_address_it_resolves_to(monkeypatch):
    def resolve(host, port):
        return [(None, None, None, "", ("192.168.1.20", 0)), (None, None, None, "", ("1.1.1.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    with pytest.raises(ConfigError):
        check_mcp_url("http://garmin.lan/mcp")


def test_an_unresolvable_name_is_an_outage_not_a_setting_error(monkeypatch):
    def fail(host, port):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(McpUnavailable, match="cannot resolve"):
        check_mcp_url("http://garmin.lan/mcp")


@pytest.mark.parametrize("url", ["http://127.0.0.1:99999/mcp", "https://garmin.example.com:-1/mcp"])
def test_a_port_out_of_range_is_a_setting_error(url):
    with pytest.raises(ConfigError, match="invalid port"):
        check_mcp_url(url)


def test_sync_reports_an_unresolvable_server_as_unreachable(monkeypatch, capsys):
    from lifter.cli import main

    def fail(host, port, *args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("GARMIN_MCP_URL", "http://garmin.lan/mcp")
    monkeypatch.setenv("GARMIN_MCP_TOKEN", "token")
    assert main(["sync", "--days", "1"]) == 3
    assert "cannot resolve the Garmin MCP server" in capsys.readouterr().out


def test_sync_reports_a_refused_token_on_one_line(monkeypatch, capsys):
    """A server that answers 401 to the MCP initialize: exit 3, one line, no traceback."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from lifter.cli import main

    class Refuses(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(401)
            self.send_header("content-length", "0")
            self.end_headers()

        do_GET = do_DELETE = do_POST

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Refuses)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
        monkeypatch.setenv("GARMIN_MCP_URL", f"http://127.0.0.1:{server.server_address[1]}/mcp")
        monkeypatch.setenv("GARMIN_MCP_TOKEN", "wrong-token")
        assert main(["sync", "--days", "1"]) == 3
        captured = capsys.readouterr()
        assert captured.out.startswith("Garmin MCP server: ")
        assert "wrong-token" not in captured.out + captured.err
        assert "Traceback" not in captured.err
    finally:
        server.shutdown()


def test_the_client_refuses_a_public_http_url():
    with pytest.raises(ConfigError):
        McpToolCaller("http://8.8.8.8/mcp", "token")


def test_sync_stops_before_sending_the_token_in_clear(monkeypatch, capsys):
    from lifter.cli import main

    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("GARMIN_MCP_URL", "http://8.8.8.8/mcp")
    monkeypatch.setenv("GARMIN_MCP_TOKEN", "token")
    assert main(["sync"]) == 2
    assert "GARMIN_MCP_URL must be https" in capsys.readouterr().out
