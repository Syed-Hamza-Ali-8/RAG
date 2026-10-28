from typing import Annotated

from fastapi import APIRouter, Depends, Request

from gateway.deps import AuthContext, get_auth_context
from gateway.models.query import QueryRequest, QueryResponse
from gateway.rag import answer_query

router = APIRouter(prefix="/v1")


@router.post("/query", response_model=QueryResponse)
async def query(
    body: QueryRequest, request: Request, auth: Annotated[AuthContext, Depends(get_auth_context)]
) -> QueryResponse:
    state = request.app.state
    return await answer_query(
        state.pool,
        state.embedder,
        state.llm,
        auth=auth,
        question=body.question,
        top_k=body.top_k or state.settings.retrieval_top_k,
        cache=state.cache,
    )
