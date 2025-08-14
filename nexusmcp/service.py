import nexusrpc
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    import mcp.types


@nexusrpc.service(name="MCP")
class MCPService:
    list_tools: nexusrpc.Operation[None, list[mcp.types.Tool]]
