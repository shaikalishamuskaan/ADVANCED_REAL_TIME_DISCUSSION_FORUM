import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.core.observability import install_logging

from app.core.redis import get_redis_client, close_redis_client
from app.notify.workers.consumer import consume_forever
from app.api.routers.notifications import router as notifications_router
from app.api.routers.realtime import router as realtime_router
from app.realtime.workers.pubsub_listener import listen_to_redis
from app.realtime.workers.identity_consumer import consume_identity_forever
from app.notify.workers.outbox_relay import run_outbox_relay
from app.notify.workers.cleanup import run_cleanup_forever
from app.core.errors import install_error_handlers

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

    pubsub_task = asyncio.create_task(listen_to_redis())
    identity_task = asyncio.create_task(consume_identity_forever())
    relay_task = asyncio.create_task(run_outbox_relay())
    cleanup_task = asyncio.create_task(run_cleanup_forever())
    try:
        yield
    finally:
        tasks = [consumer_task, pubsub_task, identity_task, relay_task, cleanup_task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_redis_client()
        logger.info("Realtime workers stopped and Redis connection closed")


app = FastAPI(
    title="Notification and Realtime Service",
    version="1.0.0",
    lifespan=lifespan,
)
install_logging(app)

install_error_handlers(app)
app.include_router(notifications_router)
app.include_router(realtime_router)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "notification_realtime",
    }
