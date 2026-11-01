from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.rate_limit import search_access
from app.core.database import get_db
from app.schemas.search import SearchQuery, SearchResponse
from app.services.search_query import search_documents

router = APIRouter(tags=["Search"])


@router.get("/api/search", response_model=SearchResponse)
async def search(
    query: Annotated[SearchQuery, Query()],
    current_user: dict = Depends(search_access),
    session: AsyncSession = Depends(get_db),
):
    return await search_documents(session, query)
