import pytest

from nexusrpc.handler import StartOperationContext
from .service import MyInput, TestServiceHandler, mcp_service


def test_tools_added_to_list() -> None:
    """Test that decorated functions are added to the tools list."""

    assert len(mcp_service.tool_services) == 1
    assert len(mcp_service.tool_services[0].tools) == 2
    assert mcp_service.tool_services[0].tools[0].func == TestServiceHandler.op1
    assert mcp_service.tool_services[0].tools[1].func == TestServiceHandler.op2


@pytest.mark.asyncio
async def test_list_tools() -> None:
    """Test that decorated functions are added to the tools list."""

    tools = await mcp_service.list_tools(
        StartOperationContext(
            service="modified-service-name",
            operation="modified-op-name",
            headers={},
            request_id="123",
        ),
        None,
    )
    assert len(tools) == 2
    assert tools[0].name == "modified-service-name.modified-op-name"
    assert tools[1].name == "modified-service-name.op2"
    assert tools[0].description == "This is a test operation."
    assert tools[1].description == "This is also a test operation."
    assert tools[0].inputSchema == MyInput.model_json_schema()
    assert tools[1].inputSchema == MyInput.model_json_schema()
