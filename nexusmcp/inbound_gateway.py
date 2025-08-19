"""
Nexus MCP Inbound Gateway

This module provides an inbound gateway that maps the Model Context Protocol (MCP) tools calls to Temporal Nexus
Operations. It enables MCP tool calls to be backed by Temporal's reliable workflow execution system.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from temporalio.client import Client
from temporalio.worker import Worker

from .proxy_workflow import (
    ToolCallInput,
    ToolCallWorkflow,
    ToolListInput,
    ToolListWorkflow,
)


class InboundGateway:
    """
    Inbound gateway for bridging MCP server requests to Temporal Nexus Operations.

    This gateway acts as an adapter between the Model Context Protocol (MCP) server and Temporal Nexus Operations,
    enabling tool calls to be executed reliably through Temporal's workflow engine. It handles both tool listing and
    tool call requests by delegating them to a corresponding set of Temporal Nexus Services in a given endpoint.
    """

    _client: Client
    """Temporal client for executing operations"""

    _endpoint: str
    """Target endpoint URL for tool operations"""

    _task_queue: str
    """Temporal task queue for executing proxy workflows"""

    def __init__(self, client: Client, endpoint: str) -> None:
        """
        Initialize the Nexus MCP Inbound Gateway.

        Args:
            client: Temporal client instance for workflow execution
            endpoint: Target endpoint URL for tool operations
        """
        self._client = client
        self._endpoint = endpoint
        self._task_queue = "nexus-proxy-queue"  # TODO: remove this when we support direct nexus client calls.

    async def _handle_list_tools(self) -> list[types.Tool]:
        """
        Handle MCP list tools request by executing the ToolListWorkflow.

        This method retrieves the list of available tools from the target endpoint
        by calling the "ListTools" Nexus Operation in the "MCP" Service.

        Returns:
            List of available Nexus operations exposed as MCP tools from the target endpoint.

        Raises:
            WorkflowFailureError: If the workflow execution fails
        """
        return await self._client.execute_workflow(
            ToolListWorkflow.run,
            arg=ToolListInput(endpoint=self._endpoint),
            id=str(uuid.uuid4()),
            task_queue=self._task_queue,
        )

    async def _handle_call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """
        Handle MCP tool call request by calling the corresponding Nexus Operation in the given endpoint.

        Args:
            name: Tool name in the format "service_operation" (LLM-compatible format)
            arguments: Dictionary of arguments to pass to the tool

        Returns:
            Result of the tool call (type depends on the specific tool)

        Raises:
            ValueError: If the tool name format is invalid (missing '_' separator)

        Example:
            result = await gateway._handle_call_tool(
                "calculator_add",
                {"a": 5, "b": 3}
            )
        """
        # Parse tool name in LLM-compatible format: "service_operation"
        # Handle MCP client prefixes by finding the actual service_operation pattern
        
        # Remove any MCP client prefix (anything before "__" if present)
        if "__" in name:
            _, _, actual_name = name.rpartition("__")
        else:
            actual_name = name
            
        # Find the first underscore in the actual tool name to split service from operation
        underscore_pos = actual_name.find('_')
        if underscore_pos == -1:
            raise ValueError(f"Invalid tool name: {name}, must be in the format 'service_operation'")
        
        service = actual_name[:underscore_pos]
        operation = actual_name[underscore_pos + 1:]
        
        if not service or not operation:
            raise ValueError(f"Invalid tool name: {name}, must be in the format 'service_operation'")
        
        # Convert service name back to original casing for Nexus operation lookup
        # Since we lowercase service names for tool naming, we need to restore original case
        # This assumes PascalCase service names (Calculator, WeatherService, etc.)
        service = service.capitalize()
        return await self._client.execute_workflow(
            ToolCallWorkflow.run,
            arg=ToolCallInput(
                endpoint=self._endpoint,
                service=service,
                operation=operation,
                arguments=arguments,
            ),
            id=str(uuid.uuid4()),
            task_queue=self._task_queue,
        )

    @asynccontextmanager
    async def run(self) -> AsyncGenerator[None, None]:
        """
        Context manager for running the Temporal worker that can execute the proxy workflows (ToolListWorkflow and
        ToolCallWorkflow).

        This method is temporary and will be removed when Temporal supports direct nexus client calls.

        Yields:
            None: Context is active while worker is running
        """
        async with Worker(
            self._client,
            task_queue=self._task_queue,
            workflows=[ToolListWorkflow, ToolCallWorkflow],
        ):
            yield

    def register(self, server: Server) -> None:
        """
        Register gateway handlers with a low level MCP server.

        This method connects the gateway's tool handling methods to the MCP server's
        routing system. Once registered, the server will delegate list_tools and
        call_tool requests to this gateway's corresponding handler methods.

        Args:
            server: MCP server instance to register handlers with

        Example:
            server = Server("my-mcp-server")
            gateway = NexusMCPInboundGateway(client, "https://api.example.com")
            gateway.register(server)
            # Server is now configured to use the gateway for tool operations
        """
        server.list_tools()(self._handle_list_tools)  # type: ignore[no-untyped-call]
        server.call_tool()(self._handle_call_tool)
