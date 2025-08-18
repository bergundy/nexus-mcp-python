import uuid
from dataclasses import dataclass

import pytest
from mcp import ClientSession
from temporalio import workflow
from temporalio.api.nexus.v1 import EndpointSpec, EndpointTarget
from temporalio.api.operatorservice.v1 import CreateNexusEndpointRequest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from nexusmcp.nexus_transport import WorkflowNexusTransport

from .service import TestServiceHandler, mcp_service


@dataclass
class MCPCallerWorkflowInput:
    endpoint: str


# TODO: disable sandbox due to use of ThreadLocal by sniffio
@workflow.defn(sandboxed=False)
class MCPCallerWorkflow:
    @workflow.run
    async def run(self, input: MCPCallerWorkflowInput) -> None:
        transport = WorkflowNexusTransport(input.endpoint)
        async with transport.connect() as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                list_tools_result = await session.list_tools()
                assert len(list_tools_result.tools) == 2
                assert list_tools_result.tools[0].name == "modified-service-name/modified-op-name"
                assert list_tools_result.tools[1].name == "modified-service-name/op2"

                call_result = await session.call_tool("modified-service-name/modified-op-name", {"name": "World"})
                assert call_result.structuredContent == {"message": "Hello, World"}


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
            workflows=[MCPCallerWorkflow],
            nexus_service_handlers=[mcp_service, TestServiceHandler()],
        ):
            await env.client.execute_workflow(
                MCPCallerWorkflow.run,
                arg=MCPCallerWorkflowInput(endpoint=endpoint_name),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
