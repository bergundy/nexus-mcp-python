# Nexus MCP

> Bridge Model Context Protocol (MCP) tools with Temporal's reliable workflow execution system via Nexus RPC.

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/protocol-MCP-green.svg)](https://modelcontextprotocol.io/)
[![Temporal](https://img.shields.io/badge/powered%20by-Temporal-purple.svg)](https://temporal.io/)

## Overview

Nexus MCP is a bridge that connects the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) with
[Temporal's Nexus RPC framework](https://docs.temporal.io/nexus). It enables MCP tools to be backed by Temporal's
reliable, durable workflow execution system, providing:

- **Reliability**: Tool executions are backed by Temporal's fault-tolerant workflows
- **Durability**: Long-running operations survive process restarts and failures
- **Observability**: Full visibility into tool execution through Temporal's UI
- **Scalability**: Distribute tool execution across multiple workers

The library acts as an adapter, allowing you to expose Temporal Nexus Operations as MCP tools.

## Key Features

- 🔗 **Seamless Integration**: Bridge MCP and Temporal with minimal configuration
- 🛠️ **Automatic Tool Discovery**: Expose Nexus Operations as MCP tools automatically
- 🔧 **Flexible Filtering**: Control which operations are exposed using decorators
- 📊 **Rich Metadata**: Automatic schema generation from Pydantic models
- 🚀 **Production Ready**: Built on proven Temporal infrastructure

## Installation

### Prerequisites

- Python 3.13+
- Access to a Temporal cluster
- MCP-compatible client (e.g., Claude Desktop, custom MCP client)

### Install via uv (recommended)

> NOTE: packages not published yet.

```bash
uv add nexus-mcp
```

### Install via pip

```bash
pip install nexus-mcp
```

### Development Installation

```bash
git clone https://github.com/bergundy/nexus-mcp-python
cd nexus-mcp
uv sync --dev
```

## Quick Start

### 1. Define Your Nexus Service at `service.py`

```python
import nexusrpc
from temporalio import workflow
from pydantic import BaseModel

class CalculateRequest(BaseModel):
    expression: str

class CalculateResponse(BaseModel):
    result: float

@nexusrpc.service(name="Calculator")
class CalculatorService:
    """A simple calculator service exposed via MCP."""

    calculate: nexusrpc.Operation[CalculateRequest, CalculateResponse]
```

### 2. Implement the Service Handler at `service_handler.py`

```python
import nexusrpc
from nexusmcp import MCPServiceHandler
from .service import CalculatorService, CalcluateRequest, CalculateResponse

mcp_service_handler = MCPServiceHandler()

@mcp_service_handler.register
@nexusrpc.handler.service_handler(service=CalculatorService)
class CalculatorHandler:
    @nexusrpc.handler.sync_operation
    async def calculate(self, _ctx: nexusrpc.handler.StartOperationContext, input: CalculateRequest) -> CalculateResponse:
        """Evaluate a mathematical expression and return the result."""
        # Your calculation logic here
        result = eval(input.expression)  # Don't use eval in production!
        return CalculateResponse(result=result)
```

### 4. Create a Nexus namespace and endpoint

**Local dev or self hosted deployment**

```bash
temporal operator namespace create --namespace my-handler-namespace
temporal operator nexus endpoint create \
  --name mcp-gateway \
  --target-namespace my-handler-namespace \
  --target-task-queue mcp
```

**Temporal Cloud**

> TODO

### 3. Set Up the Temporal Worker with the Nexus handlers at `worker.py`

```python
import asyncio

from temporalio.client import Client
from temporalio.worker import Worker
from .service_handler import mcp_service_handler, CalculatorHandler

async def main():
    # Connect to Temporal (replace host and namespace as needed).
    client = await Client.connect("localhost:7233", namespace="my-handler-namespace")

    async with Worker(
        client,
        # This task queue should be the target of a Nexus endpoint defined above.
        task_queue="mcp",
        nexus_service_handlers=[CalculatorHandler(), mcp_service_handler],
    ):
        await asyncio.Event().wait()
```

### 4. Set Up the MCP Gateway

```python
import asyncio
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from temporalio.client import Client
from nexusmcp import InboundGateway

async def main():
    server = Server("nexus-mcp-demo")
    # Connect to Temporal (replace host and namespace as needed).
    client = await Client.connect("localhost:7233", namespace="my-caller-namespace")

    # Create the MCP gateway
    gateway = InboundGateway(
        client=client,
        endpoint="mcp-gateway",
    )
    gateway.register(server)

    async with gateway.run():
        # Set up MCP server transport and run here...


if __name__ == "__main__":
    asyncio.run(main())
```

### 5. Configure Your MCP Client

Add to your MCP client configuration (e.g., Claude Desktop):

```json
{
  "mcpServers": {
    "nexus-calculator": {
      "command": "python",
      "args": ["path/to/your/mcp_server.py"]
    }
  }
}
```

### 6. Make MCP calls from a Temporal workflow

```python
import asyncio
import uuid

from mcp import ClientSession
from nexusmcp import WorkflowNexusTransport
from pydantic import BaseModel
from temporalio import workflow
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker


class AgentWorkflowInput(BaseModel):
    endpoint: str


@workflow.defn(sandboxed=False)
class AgentWorkflow:
    @workflow.run
    async def run(self, input: AgentWorkflowInput):
        transport = WorkflowNexusTransport(input.endpoint)
        async with transport.connect() as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                list_tools_result = await session.list_tools()
                print(f"available tools: {list_tools_result}")


async def main():
    client = await Client.connect(
        "localhost:7233",
        data_converter=pydantic_data_converter,
    )

    async with Worker(
        client,
        task_queue="agent-workflow",
        workflows=[AgentWorkflow],
    ) as worker:
        await client.execute_workflow(
            AgentWorkflow.run,
            AgentWorkflowInput(endpoint="mcp-gateway"),
            id=str(uuid.uuid4()),
            task_queue=worker.task_queue,
        )
```

## Usage Examples

### Tool Filtering

Control which operations are exposed using the `@exclude` decorator:

```python
import nexusrpc
from nexusmcp import MCPServiceHandler, exclude

mcp_service_handler = MCPServiceHandler()


@mcp_service_handler.register
@nexusrpc.handler.service_handler()
class CalculatorHandler:
    @exclude
    @nexusrpc.handler.sync_operation
    async def private_operation(self, _ctx: nexusrpc.handler.StartOperationContext, input: SomeModel) -> SomeModel:
        """This won't be available to MCP clients."""
        pass

    @nexusrpc.handler.sync_operation
    async def public_operation(self, _ctx: nexusrpc.handler.StartOperationContext, input: SomeModel) -> SomeModel:
        """This will be available as an MCP tool."""
        pass
```

## Development

### Setting Up Development Environment

```bash
# Install dependencies
uv sync --dev
```

### Running Tests

```bash
# Run all tests
uv run pytest
```

### Code Quality

```bash
# Format code
uv run ruff format

# Lint code
uv run ruff check

# Type checking
uv run mypy .
```

## License

This project is licensed under the MIT License. See the LICENSE file for details.
