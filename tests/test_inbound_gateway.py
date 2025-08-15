import asyncio

import anyio
from mcp.shared.message import SessionMessage
import pytest
from mcp import ClientSession
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from temporalio.api.nexus.v1 import EndpointSpec, EndpointTarget
from temporalio.api.operatorservice.v1 import CreateNexusEndpointRequest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from nexusmcp import InboundGateway

from .service import TestServiceHandler, mcp_service


@pytest.mark.asyncio
async def test_inbound_gateway() -> None:
    server = Server("test-tools")

    endpoint_name = "endpoint"
    task_queue = "handler-queue"

    async with await WorkflowEnvironment.start_local() as env:
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
        gateway = InboundGateway(env.client, endpoint_name)
        gateway.register(server)

        worker = Worker(
            env.client,
            task_queue=task_queue,
            nexus_service_handlers=[TestServiceHandler(), mcp_service],
        )

        async with gateway.run(), worker:
            server_write, client_read = anyio.create_memory_object_stream(0)  # type: ignore[var-annotated]
            client_write, server_read = anyio.create_memory_object_stream(0)  # type: ignore[var-annotated]

            init_options = InitializationOptions(
                server_name=server.name,
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            )
            await asyncio.gather(
                server.run(server_read, server_write, init_options),
                call_tool(client_read, client_write),
            )


async def call_tool(
    read_stream: anyio.streams.memory.MemoryObjectReceiveStream[SessionMessage],
    write_stream: anyio.streams.memory.MemoryObjectSendStream[SessionMessage],
) -> None:
    """Test MCP client connecting via memory streams and calling tools."""
    async with ClientSession(read_stream, write_stream) as session:
        # Initialize the session
        await session.initialize()

        # List available tools
        list_tools_result = await session.list_tools()
        print(f"Available tools: {[tool.name for tool in list_tools_result.tools]}")

        assert len(list_tools_result.tools) == 2
        assert list_tools_result.tools[0].name == "modified-service-name.modified-op-name"
        assert list_tools_result.tools[1].name == "modified-service-name.op2"

        call_result = await session.call_tool("modified-service-name.modified-op-name", {"name": "World"})
        assert call_result.structuredContent == {"message": "Hello, World"}
