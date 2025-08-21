from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_connected_server_and_client_session
from temporalio import workflow

from nexusmcp.service import MCPService


class MCPClient:
    """
    An MCP client for use in Temporal workflows.

    This class provides a client that proxies MCP traffic from a Temporal Workflow to a Temporal
    Nexus service. It works by running an MCP server in the workflow whose handlers delegate to
    nexus operations, and connecting to it via an in-memory transport.

    Example:
        ```python
        client = MCPClient("my-endpoint")
        async with client.connect() as session:
            await session.list_tools()
            await session.call_tool("my-service_my-operation", {"arg": "value"})
        ```
    """

    def __init__(
        self,
        endpoint: str,
    ):
        self.endpoint = endpoint
        # Run an in-workflow MCP server whose handlers make nexus calls
        self.mcp_server = Server("workflow-gateway-mcp-server")
        self.mcp_server.list_tools()(self._handle_list_tools)  # type: ignore[no-untyped-call]
        self.mcp_server.call_tool()(self._handle_call_tool)

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[ClientSession, None]:
        """
        Create a connected MCP ClientSession.

        The session is automatically initialized before being yielded.
        """
        async with create_connected_server_and_client_session(
            self.mcp_server,
            raise_exceptions=True,
        ) as session:
            yield session

    async def _handle_list_tools(self) -> list[types.Tool]:
        nexus_client = workflow.create_nexus_client(
            endpoint=self.endpoint,
            service=MCPService,
        )
        return await nexus_client.execute_operation(MCPService.list_tools, None)

    async def _handle_call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        service, _, operation = name.partition("_")
        nexus_client = workflow.create_nexus_client(
            endpoint=self.endpoint,
            service=service,
        )
        return await nexus_client.execute_operation(operation, arguments)
