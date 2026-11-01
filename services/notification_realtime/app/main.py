import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.redis import get_redis_client, close_redis_client
from app.notify.workers.consumer import consume_forever
from app.api.routers.notifications import router as notifications_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis = get_redis_client()

    # Verify Redis connectivity before starting the worker.
    await redis.ping()
    logger.info("Redis connection successful")

    # Start the Notify Redis Stream consumer in the background.
    consumer_task = asyncio.create_task(consume_forever())
    logger.info("Notify consumer background task started")

    yield

    # Stop the worker gracefully during application shutdown.
    consumer_task.cancel()

    try:
        await consumer_task
    except asyncio.CancelledError:
        logger.info("Notify consumer stopped")

    await close_redis_client()
    logger.info("Redis connection closed")


app = FastAPI(
    title="Notification and Realtime Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(notifications_router)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "notification_realtime",
    }