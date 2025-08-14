from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    import mcp.types

    from .service import MCPService

from pydantic import BaseModel


class ToolListInput(BaseModel):
    endpoint: str
    pass


class ToolCallInput(BaseModel):
    endpoint: str
    service: str
    operation: str
    arguments: dict[str, Any]


class ProxyWorkflowInput(BaseModel):
    action: ToolListInput | ToolCallInput


@workflow.defn
class ToolListWorkflow:
    @workflow.run
    async def run(self, input: ToolListInput) -> list[mcp.types.Tool]:
        client = workflow.create_nexus_client(
            endpoint=input.endpoint,
            service=MCPService,
        )
        return await client.execute_operation(MCPService.list_tools, None)


@workflow.defn
class ToolCallWorkflow:
    @workflow.run
    async def run(self, input: ToolCallInput) -> Any:
        client = workflow.create_nexus_client(
            endpoint=input.endpoint,
            service=input.service,
        )
        return await client.execute_operation(input.operation, input.arguments)
