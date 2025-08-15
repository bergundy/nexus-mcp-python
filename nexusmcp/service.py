"""
MCP Nexus Service Definition

This module defines the Nexus RPC Service interface for MCP (Model Context Protocol) operations.
The service provides an Operation for listing Nexus Operations exposed as MCP tools.
"""

import nexusrpc
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    import mcp.types


@nexusrpc.service(name="MCP")
class MCPService:
    """
    Nexus RPC service for MCP (Model Context Protocol) operations.

    This service defines the interface for MCP-related Operations that can be invoked
    through Temporal's Nexus RPC framework. It provides a bridge between Temporal
    workflows and MCP protocol Operations.
    """

    list_tools: nexusrpc.Operation[None, list[mcp.types.Tool]] = nexusrpc.Operation(name="ListTools")
    """
    Operation to retrieve a list of available Nexus Operations exposed as MCP tools.

    This operation takes no input parameters and returns a list of MCP Tool objects
    that represent the available Operations and their capabilities.

    Returns:
        list[mcp.types.Tool]: A list of available MCP Tools with their metadata,
                             schemas, and capabilities.
    """
