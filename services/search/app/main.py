import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.core.observability import install_logging
from sqlalchemy import text

from app.core.database import engine
from app.core.redis import close_redis_client, get_redis_client
from app.workers.index_consumer import consume_forever
from app.api.routers.search import router as search_router
from app.core.errors import install_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    consumer_task = None
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        await get_redis_client().ping()
        consumer_task = asyncio.create_task(consume_forever())
        yield
    finally:
        if consumer_task is not None:
            consumer_task.cancel()
            await asyncio.gather(consumer_task, return_exceptions=True)
        try:
            await close_redis_client()
        finally:
            await engine.dispose()


app = FastAPI(title="Search Service", version="1.0.0", lifespan=lifespan)
install_logging(app)
install_error_handlers(app)
app.include_router(search_router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "search"}
