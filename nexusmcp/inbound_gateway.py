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


class NexusMCPInboundGateway:
    client: Client
    endpoint: str
    task_queue: str

    def __init__(self, client: Client, endpoint: str):
        self.client = client
        self.endpoint = endpoint
        self.task_queue = "nexus-proxy-queue"  # TODO: remove this when we support direct nexus client calls.

    async def handle_list_tools(self) -> list[types.Tool]:
        return await self.client.execute_workflow(
            ToolListWorkflow.run,
            arg=ToolListInput(endpoint=self.endpoint),
            id=str(uuid.uuid4()),
            task_queue=self.task_queue,
        )

    async def handle_call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        service, operation = name.split(".", maxsplit=1)
        return await self.client.execute_workflow(
            ToolCallWorkflow.run,
            arg=ToolCallInput(
                endpoint=self.endpoint,
                service=service,
                operation=operation,
                arguments=arguments,
            ),
            id=str(uuid.uuid4()),
            task_queue=self.task_queue,
        )

    @asynccontextmanager
    async def run(self) -> AsyncGenerator[None]:
        async with Worker(
            self.client,
            task_queue=self.task_queue,
            workflows=[ToolListWorkflow, ToolCallWorkflow],
        ):
            yield

    def register(self, server: Server) -> None:
        server.list_tools()(self.handle_list_tools)  # type: ignore[no-untyped-call]
        server.call_tool()(self.handle_call_tool)
