"""
Service Handler for MCP-Nexus Bridge

This module provides a Nexus Service Handler that can be used to expose Nexus services as MCP tools.

The main components include:
- _Tool and _ToolService data structures for organizing service operations
- MCPServiceHandler for managing a catalog of operations to be exposed as MCP tools
- Decorators for controlling which operations are exposed as MCP tools
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import mcp.types
import nexusrpc
import pydantic

from .service import MCPService

# Set up logging
logger = logging.getLogger(__name__)

# Compile regex patterns ahead of time for better performance
_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_SERVICE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9-]{1,64}$")


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
        # Generate LLM-compatible tool name using underscores instead of forward slashes
        tool_name = f"{service.name}_{self.defn.name}"

        # Validate tool name meets LLM provider requirements
        if not _is_valid_tool_name(tool_name):
            raise ValueError(
                f"Generated tool name '{tool_name}' does not meet LLM provider requirements. "
                f"Tool names must match pattern ^[a-zA-Z0-9_-]{{1,64}}$ for Claude Desktop or ^[a-zA-Z0-9_-]{{1,128}}$ for other clients."
            )

        return mcp.types.Tool(
            name=tool_name,
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
        # Validate service name contains only characters that will create valid tool names
        if not _is_valid_service_name(service_defn.name):
            invalid_chars = set(service_defn.name) - set(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
            )
            raise ValueError(
                f"Service name '{service_defn.name}' contains invalid characters {invalid_chars}. "
                f"Only alphanumeric characters and hyphens are allowed for LLM provider compatibility."
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
        tools = [tool.to_mcp_tool(service.defn) for service in self._tool_services for tool in service.tools]
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"MCP.list_tools found {len(tools)} tools: {[tool.name for tool in tools]}")
        return tools


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


def _is_valid_tool_name(name: str) -> bool:
    """Validate tool name against LLM provider requirements.

    Tool names must match the pattern ^[a-zA-Z0-9_-]{1,64}$ for Claude Desktop
    or ^[a-zA-Z0-9_-]{1,128}$ for other clients (Goose, OpenAI, etc.).
    Validates against the most restrictive (64 chars) for maximum compatibility.

    Args:
        name: The tool name to validate

    Returns:
        True if the name is valid, False otherwise
    """
    return bool(_TOOL_NAME_PATTERN.match(name))


def _is_valid_service_name(name: str) -> bool:
    """Validate service name for tool naming compatibility.

    Service names cannot contain underscores as they are used to
    split service names from operation names when creating tool names.

    Args:
        name: The service name to validate

    Returns:
        True if the service name is valid, False otherwise
    """
    # Service names cannot contain underscores (used as delimiter)
    return bool(_SERVICE_NAME_PATTERN.match(name))
