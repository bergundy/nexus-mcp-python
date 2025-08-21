import asyncio
import uuid
from dataclasses import dataclass

import pytest
from mcp.types import CallToolResult, ListToolsResult
from nexusrpc import Operation, service
from nexusrpc.handler import StartOperationContext, service_handler, sync_operation
from pydantic import BaseModel
from temporalio import nexus, workflow
from temporalio.api.nexus.v1 import EndpointSpec, EndpointTarget
from temporalio.api.operatorservice.v1 import CreateNexusEndpointRequest
from temporalio.client import WithStartWorkflowOperation
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

import nexusmcp.workflow
from nexusmcp import MCPServiceHandler

mcp_service = MCPServiceHandler()


@dataclass
class AppendInput:
    session_id: str
    value: int


class AppendOutput(BaseModel):
    data: list[int]


@service
class TestService:
    append: Operation[AppendInput, AppendOutput]


@workflow.defn(sandboxed=False)
class AppendWorkflow:
    def __init__(self):
        self.data = []

    @workflow.run
    async def run(self) -> None:
        await asyncio.Event().wait()

    @workflow.update
    async def append(self, input: int) -> AppendOutput:
        self.data.append(input)
        return AppendOutput(data=self.data)


@mcp_service.register
@service_handler(service=TestService)
class TestServiceHandler:
    @sync_operation
    async def append(self, ctx: StartOperationContext, input: AppendInput) -> AppendOutput:
        # TODO: Should we use a custom ClientSession and start the workflow in initialize()?
        # wf = nexus.client().get_workflow_handle_for(AppendWorkflow.run, input.session_id)
        with_start = WithStartWorkflowOperation(
            AppendWorkflow.run,
            id=input.session_id,
            task_queue=nexus.info().task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
        return await nexus.client().execute_update_with_start_workflow(
            AppendWorkflow.append,
            input.value,
            start_workflow_operation=with_start,
        )


@dataclass
class MCPCallerWorkflowInput:
    endpoint: str


class MCPCallerWorkflowOutput(BaseModel):
    list_tools_result: ListToolsResult
    call_tool_results: list[CallToolResult]


# sandbox disabled due to use of ThreadLocal by sniffio
# TODO: make this unnecessary
@workflow.defn(sandboxed=False)
class MCPCallerWorkflow:
    @workflow.run
    async def run(self, input: MCPCallerWorkflowInput) -> MCPCallerWorkflowOutput:
        async with nexusmcp.workflow.MCPClient(input.endpoint).connect() as session:
            list_tools_result = await session.list_tools()
            call_tool_result_1 = await session.call_tool("TestService_append", {"session_id": "123", "value": 1})
            call_tool_result_2 = await session.call_tool("TestService_append", {"session_id": "123", "value": 2})
            return MCPCallerWorkflowOutput(
                list_tools_result=list_tools_result,
                call_tool_results=[call_tool_result_1, call_tool_result_2],
            )


@pytest.mark.asyncio
async def test_workflow_caller() -> None:
    endpoint_name = "endpoint"
    task_queue = "handler-queue"

    async with await WorkflowEnvironment.start_local(data_converter=pydantic_data_converter) as env:
        await env.client.operator_service.create_nexus_endpoint(
            CreateNexusEndpointRequest(
                spec=EndpointSpec(
                    name=endpoint_name,
                    target=EndpointTarget(
                        worker=EndpointTarget.Worker(
                            namespace=env.client.namespace,
                            task_queue=task_queue,
                        )
                    ),
                )
            )
        )

        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[MCPCallerWorkflow, AppendWorkflow],
            nexus_service_handlers=[mcp_service, TestServiceHandler()],
        ):
            result = await env.client.execute_workflow(
                MCPCallerWorkflow.run,
                arg=MCPCallerWorkflowInput(endpoint=endpoint_name),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
            assert len(result.list_tools_result.tools) == 1
            assert result.list_tools_result.tools[0].name == "TestService_append"
            assert result.call_tool_results[0].structuredContent == {"data": [1]}
            assert result.call_tool_results[1].structuredContent == {"data": [1, 2]}
