from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers.comments import router as comments_router
from app.core.redis import get_redis_client
from app.api.routers.threads import router as threads_router
from app.api.routers.thread_queries import router as thread_queries_router
from app.api.routers.thread_details import router as thread_details_router
from app.api.routers.thread_edits import router as thread_edits_router
from app.api.routers.thread_deletions import (
    router as thread_deletions_router,
)
from app.api.routers.thread_likes import router as thread_likes_router
from app.api.routers.comment_likes import router as comment_likes_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = get_redis_client()

    # Check Redis connectivity when the service starts.
    await redis_client.ping()

    yield

    # Close Redis connections when the service stops.
    await redis_client.aclose()


app = FastAPI(
    title="Discussion Service",
    description="Core discussion management service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {
        "service": "discussion",
        "status": "healthy",
    }


app.include_router(comments_router)
app.include_router(threads_router)
app.include_router(thread_queries_router)
app.include_router(thread_details_router)
app.include_router(thread_edits_router)
app.include_router(thread_deletions_router)
app.include_router(thread_likes_router)
app.include_router(comment_likes_router)