"""The Garmin MCP URL: no bearer token in clear outside the loopback and private networks."""

import socket

import pytest

from lifter.config import ConfigError
from lifter.garmin import McpToolCaller, check_mcp_url


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


def test_an_unresolvable_name_is_refused(monkeypatch):
    def fail(host, port):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(ConfigError):
        check_mcp_url("http://garmin.lan/mcp")


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
