from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import mcp.types
import nexusrpc
import pydantic

from .service import MCPService


@dataclass
class Tool:
    func: Callable[..., Any]
    defn: nexusrpc.Operation[Any, Any]

    def to_mcp_tool(self, service: nexusrpc.ServiceDefinition) -> mcp.types.Tool:
        return mcp.types.Tool(
            name=f"{service.name}.{self.defn.name}",
            description=(self.func.__doc__.strip() if self.func.__doc__ is not None else None),
            inputSchema=(
                self.defn.input_type.model_json_schema()
                if self.defn.input_type is not None and issubclass(self.defn.input_type, pydantic.BaseModel)
                else {}
            ),
        )


@dataclass
class ToolService:
    defn: nexusrpc.ServiceDefinition
    tools: list[Tool]


@nexusrpc.handler.service_handler(service=MCPService)
class MCPServiceHandler:
    tool_services: list[ToolService]

    def __init__(self) -> None:
        self.tool_services = []

    def tool_service(self, cls: type) -> type:
        service_defn = nexusrpc.get_service_definition(cls)
        if service_defn is None:
            raise ValueError(f"Class {cls.__name__} is not a Nexus Service")

        tools: list[Tool] = []
        for op in service_defn.operations.values():
            attr_name = op.method_name or op.name
            attr = getattr(cls, attr_name)
            if not callable(attr):
                raise ValueError(f"Attribute {attr_name} is not callable")
            if not getattr(attr, "__nexus_mcp_tool__", True):
                continue
            tools.append(Tool(attr, op))

        self.tool_services.append(ToolService(tools=tools, defn=service_defn))
        return cls

    @nexusrpc.handler.sync_operation
    async def list_tools(self, _ctx: nexusrpc.handler.StartOperationContext, _input: None) -> list[mcp.types.Tool]:
        return [tool.to_mcp_tool(service.defn) for service in self.tool_services for tool in service.tools]


ExcludedCallable = Callable[..., Any]


def exclude(fn: ExcludedCallable) -> ExcludedCallable:
    """
    Decorate a function to exclude it from the MCP inventory.
    """
    setattr(fn, "__nexus_mcp_tool__", False)
    return fn
