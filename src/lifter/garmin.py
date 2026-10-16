"""Client for the Garmin MCP server (garmin-mcp-remote), restricted to read tools."""

import ipaddress
import socket
from contextlib import AsyncExitStack
from typing import Any, Protocol
from urllib.parse import urlsplit

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from lifter.config import ConfigError

# The only tools the sync may call. Write tools (schedule_workout, ...) come later,
# behind human approval, and are refused here.
READ_TOOLS = frozenset(
    {
        "get_activities_by_date",
        "get_activity",
        "get_activity_hr_in_timezones",
        "get_sleep_summary",
        "get_hrv_data",
        "get_stats",
        "get_training_readiness",
        "get_training_status",
        "get_scheduled_workouts",
    }
)


# Tailscale and other overlay networks hand out addresses in the shared range, which Python does
# not count as private; traffic there is encrypted by the overlay.
SHARED_RANGE = ipaddress.ip_network("100.64.0.0/10")


def _on_private_network(host: str) -> bool:
    """Every address `host` resolves to is loopback, private, link-local or in SHARED_RANGE."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addresses = {ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos}
    return bool(addresses) and all(
        a.is_loopback or a.is_private or a.is_link_local or a in SHARED_RANGE for a in addresses
    )


def check_mcp_url(url: str) -> None:
    """The bearer token travels in a header: refuse plain HTTP outside the loopback and private
    networks (https is accepted anywhere)."""
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return
    if parts.scheme == "http" and parts.hostname and _on_private_network(parts.hostname):
        return
    raise ConfigError(
        "GARMIN_MCP_URL must be https, or http on the loopback or a private network"
        " (the bearer token would travel in clear)"
    )


class ToolError(RuntimeError):
    """The MCP server reported a failed tool call."""


class ToolCaller(Protocol):
    async def call(self, tool: str, arguments: dict[str, Any]) -> str: ...


class McpToolCaller:
    """Calls the Garmin MCP server over streamable HTTP with a bearer token."""

    def __init__(self, url: str, token: str, allowed_tools: frozenset[str] = READ_TOOLS):
        check_mcp_url(url)
        self.url = url
        self._token = token
        self.allowed_tools = allowed_tools
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "McpToolCaller":
        self._stack = AsyncExitStack()
        http = await self._stack.enter_async_context(
            create_mcp_http_client(headers={"Authorization": f"Bearer {self._token}"})
        )
        read, write = await self._stack.enter_async_context(
            streamable_http_client(self.url, http_client=http)
        )
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    async def call(self, tool: str, arguments: dict[str, Any]) -> str:
        if tool not in self.allowed_tools:
            raise PermissionError(f"tool not allowed: {tool}")
        if self._session is None:
            raise RuntimeError("use McpToolCaller as an async context manager")
        try:
            result = await self._session.call_tool(tool, arguments)
        except Exception as exc:  # transport or protocol failure: one failed call, not a crash
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc
        text = "".join(c.text for c in result.content if getattr(c, "type", None) == "text")
        if result.is_error:
            raise ToolError(text)
        return text
