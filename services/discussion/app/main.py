from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers.comments import router as comments_router
from app.core.redis import get_redis_client
from app.api.routers.threads import router as threads_router


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
