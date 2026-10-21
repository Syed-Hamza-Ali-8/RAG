from fastapi import APIRouter, Request

from gateway.models.query import QueryRequest, QueryResponse
from gateway.rag import answer_query

router = APIRouter(prefix="/v1")


@router.post("/query", response_model=QueryResponse)
async def query(body: QueryRequest, request: Request) -> QueryResponse:
    state = request.app.state
    return await answer_query(
        state.pool,
        state.embedder,
        state.llm,
        tenant_slug=body.tenant,
        question=body.question,
        top_k=body.top_k or state.settings.retrieval_top_k,
    )
