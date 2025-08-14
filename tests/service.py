from nexusrpc import Operation, service
from nexusrpc.handler import StartOperationContext, service_handler, sync_operation
from pydantic import BaseModel

from nexusmcp import MCPServiceHandler, exclude


class MyInput(BaseModel):
    name: str


class MyOutput(BaseModel):
    message: str


@service(name="modified-service-name")
class TestService:
    op1: Operation[MyInput, MyOutput] = Operation(name="modified-op-name")
    op2: Operation[MyInput, MyOutput]
    op3: Operation[MyInput, MyOutput]


mcp_service = MCPServiceHandler()


@mcp_service.tool_service
@service_handler(service=TestService)
class TestServiceHandler:
    # @nexus.workflow_run_operation
    # async def op1(
    #     self, ctx: nexus.WorkflowRunOperationContext, input: TestInput
    # ) -> TestOutput:
    #     """
    #     This is a test operation.
    #     """
    #     return TestOutput(message=f"Hello, {input.name}")

    @sync_operation
    async def op1(self, ctx: StartOperationContext, input: MyInput) -> MyOutput:
        """
        This is a test operation.
        """
        return MyOutput(message=f"Hello, {input.name}")

    @sync_operation
    async def op2(self, ctx: StartOperationContext, input: MyInput) -> MyOutput:
        """
        This is also a test operation.
        """
        return MyOutput(message=f"Hello, {input.name}")

    @exclude
    @sync_operation
    async def op3(self, ctx: StartOperationContext, input: MyInput) -> MyOutput:
        """
        This is also a test operation.
        """
        return MyOutput(message=f"Hello, {input.name}")
