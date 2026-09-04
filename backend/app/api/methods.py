from fastapi import APIRouter, Request

from app.schemas.methods import MethodsResponse

router = APIRouter(prefix="/methods", tags=["methods"])


@router.get("", response_model=MethodsResponse)
async def methods(request: Request) -> MethodsResponse:
    return MethodsResponse(methods=await request.app.state.method_registry.list_methods())
