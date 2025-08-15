"""
Service Handler for MCP-Nexus Bridge

This module provides a Nexus Service Handler that can be used to expose Nexus services as MCP tools.

The main components include:
- _Tool and _ToolService data structures for organizing service operations
- MCPServiceHandler for managing a catalog of operations to be exposed as MCP tools
- Decorators for controlling which operations are exposed as MCP tools
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import mcp.types
import nexusrpc
import pydantic

from .service import MCPService


@dataclass
class _Tool:
    """
    Represents a single tool that can be exposed through MCP.

    A Tool wraps a Nexus RPC Operation and its associated handler factory or handler function, providing the necessary
    information to convert it into an MCP tool.

    Attributes:
        func: The callable function that implements the tool's functionality
        defn: The Nexus RPC Operation definition containing metadata
    """

    func: Callable[..., Any]
    defn: nexusrpc.Operation[Any, Any]

    def to_mcp_tool(self, service: nexusrpc.ServiceDefinition) -> mcp.types.Tool:
        """
        Convert this Tool into an MCP Tool format.

        Creates an MCP-compatible tool definition from the Nexus Operation,
        including the tool name (service/operation), description from the
        function's docstring, and input schema from the Operation's type.

        Args:
            service: The service definition this tool belongs to

        Returns:
            An MCP Tool object ready for use by MCP clients
        """
        return mcp.types.Tool(
            name=f"{service.name}/{self.defn.name}",
            description=(self.func.__doc__.strip() if self.func.__doc__ is not None else None),
            inputSchema=(
                self.defn.input_type.model_json_schema()
                if self.defn.input_type is not None and issubclass(self.defn.input_type, pydantic.BaseModel)
                else {}
            ),
        )


@dataclass
class _ToolService:
    """
    Represents a collection of tools from a single Nexus service.

    Groups all the tools (operations) that belong to a specific Nexus service,
    along with the service definition containing metadata about the service.

    Attributes:
        defn: The Nexus service definition containing service metadata
        tools: List of Tool objects representing the service's operations
    """

    defn: nexusrpc.ServiceDefinition
    tools: list[_Tool]


@nexusrpc.handler.service_handler(service=MCPService)
class MCPServiceHandler:
    """
    Main service handler that manages the bridge between Nexus RPC and MCP.

    This class is responsible for:
    - Registering Nexus Services as MCP tool collections
    - Converting Nexus Operations into MCP tools
    - Providing the list of available tools via a Nexus RPC Operation
    - Validating Service definitions and Operation compatibility
    """

    _tool_services: list[_ToolService]
    """List of registered _ToolService instances"""

    def __init__(self) -> None:
        """Initialize the service handler with an empty tool registry."""
        self._tool_services = []

    def register(self, cls: type) -> type:
        """
        Register a Nexus service class to be exposed as MCP tools.

        This method acts as a decorator that processes a Nexus service class,
        extracts its operations, and registers them as MCP tools. Each operation
        becomes a tool unless explicitly excluded with the @exclude decorator.

        Args:
            cls: The Nexus service class to register

        Returns:
            The same class, unmodified (decorator pattern)

        Raises:
            ValueError: If the class is not a valid Nexus service, if the service
                       name contains '/' characters, or if an operation method
                       is not callable
        """
        service_defn = nexusrpc.get_service_definition(cls)
        if service_defn is None:
            raise ValueError(f"Class {cls.__name__} is not a Nexus Service")
        if "/" in service_defn.name:
            raise ValueError(
                f"Service name {service_defn.name} cannot contain '/' as it is used to separate service and operation names in MCP tools"
            )

        tools: list[_Tool] = []
        for op in service_defn.operations.values():
            attr_name = op.method_name or op.name
            attr = getattr(cls, attr_name)
            if not callable(attr):
                raise ValueError(f"Attribute {attr_name} is not callable")
            # Skip operations marked with @exclude decorator
            if not getattr(attr, "__nexus_mcp_tool__", True):
                continue
            tools.append(_Tool(attr, op))

        self._tool_services.append(_ToolService(tools=tools, defn=service_defn))
        return cls

    @nexusrpc.handler.sync_operation
    async def list_tools(self, _ctx: nexusrpc.handler.StartOperationContext, _input: None) -> list[mcp.types.Tool]:
        """
        List all available MCP tools from registered services.

        This operation is expected to be called via the inbound gateway to discover all available tools. It converts all
        registered Nexus Operations into MCP tool definitions.

        Args:
            _ctx: The operation context (unused)
            _input: No input required (unused)

        Returns:
            List of MCP Tool objects representing all available Operations
        """
        return [tool.to_mcp_tool(service.defn) for service in self._tool_services for tool in service.tools]


ExcludedCallable = Callable[..., Any]
"""Type alias for functions that can be excluded from MCP tool exposure"""


def exclude(fn: ExcludedCallable) -> ExcludedCallable:
    """
    Decorator to exclude a Nexus Operation from being exposed as an MCP tool.

    When applied to a method in a Nexus Service, this decorator prevents the Operation from being registered as an MCP
    tool, even though it remains available for direct Nexus RPC calls.

    Args:
        fn: The function/method to exclude from MCP tool exposure

    Returns:
        The same function, with exclusion metadata attached

    Example:
        ```python
        @nexusrpc.handler.service_handler(service=MyService)
        class MyServiceHandler:
            @nexusrpc.handler.sync_operation
            def public_operation(self, _ctx: nexusrpc.handler.StartOperationContext, _input: None) -> None:
                # This will be exposed as an MCP tool
                pass

            @exclude
            @nexusrpc.handler.sync_operation
            def internal_operation(self, _ctx: nexusrpc.handler.StartOperationContext, _input: None) -> None:
                # This will NOT be exposed as an MCP tool
                pass
        ```
    """
    setattr(fn, "__nexus_mcp_tool__", False)
    return fn
