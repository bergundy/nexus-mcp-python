import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import anyio
import mcp.types as types
import pydantic
from mcp.shared.message import SessionMessage
from temporalio import workflow

from .service import MCPService


class WorkflowNexusTransport:
    """
    Nexus MCP Transport for use in Temporal workflows.

    This class provides a transport that proxies MCP requests to a Temporal Nexus service. It can be
    used to make MCP calls via `mcp.ClientSession` from Temporal workflow code.

    Example:
        ```python
        async with WorkflowNexusTransport("my-endpoint") as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.list_tools()
                await session.call_tool("my-service/my-operation", {"arg": "value"})
        ```
    """

    def __init__(
        self,
        endpoint: str,
    ):
        self.endpoint = endpoint

    @asynccontextmanager
    async def connect(
        self,
    ) -> AsyncGenerator[
        tuple[
            anyio.streams.memory.MemoryObjectReceiveStream[SessionMessage],
            anyio.streams.memory.MemoryObjectSendStream[SessionMessage],
        ],
        None,
    ]:
        client_write, transport_read = anyio.create_memory_object_stream(0)  # type: ignore[var-annotated]
        transport_write, client_read = anyio.create_memory_object_stream(0)  # type: ignore[var-annotated]

        async def message_router() -> None:
            try:
                async for session_message in transport_read:
                    request = session_message.message.root
                    if not isinstance(request, types.JSONRPCRequest):
                        continue
                    result: types.Result | types.ErrorData
                    try:
                        match request:
                            case types.JSONRPCRequest(method="initialize"):
                                result = self._handle_initialize(
                                    types.InitializeRequestParams.model_validate(request.params)
                                )
                            case types.JSONRPCRequest(method="tools/list"):
                                result = await self._handle_list_tools()
                            case types.JSONRPCRequest(method="tools/call"):
                                result = await self._handle_call_tool(
                                    types.CallToolRequestParams.model_validate(request.params)
                                )
                            case _:
                                result = types.ErrorData(
                                    code=types.METHOD_NOT_FOUND, message=f"Unknown method: {request.method}"
                                )
                    except pydantic.ValidationError as e:
                        result = types.ErrorData(code=types.INVALID_PARAMS, message=f"Invalid request: {e}")

                    match result:
                        case types.Result():
                            response = self._json_rpc_result_response(request, result)
                        case types.ErrorData():
                            response = self._json_rpc_error_response(request, result)

                    await transport_write.send(SessionMessage(types.JSONRPCMessage(root=response)))

            except anyio.ClosedResourceError:
                pass
            finally:
                await transport_write.aclose()

        router_task = asyncio.create_task(message_router())

        try:
            yield client_read, client_write
        finally:
            await client_write.aclose()
            router_task.cancel()
            try:
                await router_task
            except asyncio.CancelledError:
                pass
            await transport_read.aclose()

    def _handle_initialize(self, params: types.InitializeRequestParams) -> types.InitializeResult:
        # TODO: MCPService should implement this
        return types.InitializeResult(
            protocolVersion="2024-11-05",
            capabilities=types.ServerCapabilities(tools=types.ToolsCapability()),
            serverInfo=types.Implementation(
                name="nexus-mcp-transport",
                version="0.1.0",
            ),
        )

    async def _handle_list_tools(self) -> types.ListToolsResult:
        nexus_client = workflow.create_nexus_client(
            endpoint=self.endpoint,
            service=MCPService,
        )
        tools = await nexus_client.execute_operation(MCPService.list_tools, None)
        return types.ListToolsResult(tools=tools)

    async def _handle_call_tool(self, params: types.CallToolRequestParams) -> types.CallToolResult:
        service, _, operation = params.name.partition("/")
        nexus_client = workflow.create_nexus_client(
            endpoint=self.endpoint,
            service=service,
        )
        result: Any = await nexus_client.execute_operation(
            operation,
            params.arguments or {},
        )
        if isinstance(result, dict):
            return types.CallToolResult(content=[], structuredContent=result)
        else:
            return types.CallToolResult(content=[types.TextContent(type="text", text=str(result))])

    def _json_rpc_error_response(self, request: types.JSONRPCRequest, error: types.ErrorData) -> types.JSONRPCResponse:
        return types.JSONRPCResponse.model_validate(
            {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": error.model_dump(),
            }
        )

    def _json_rpc_result_response(self, request: types.JSONRPCRequest, result: types.Result) -> types.JSONRPCResponse:
        return types.JSONRPCResponse.model_validate(
            {
                "jsonrpc": "2.0",
                "id": request.id,
                "result": result.model_dump(),
            }
        )
