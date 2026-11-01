import asyncio
from collections import deque
from time import monotonic
from typing import Literal
from uuid import UUID

import httpx
from anyio import CancelScope
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from redis.exceptions import RedisError

from app.api.dependencies.auth import verify_access_token
from app.clients.identity import fetch_user_status
from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.realtime.connection_manager import manager

router = APIRouter()
AUTH_TIMEOUT = 5
HEARTBEAT_INTERVAL = 30
PONG_TIMEOUT = 60
MESSAGE_LIMIT = 20


class AuthMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["auth"]
    token: str


class ClientMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["subscribe", "unsubscribe", "ping", "pong"]
    thread_id: UUID | None = None

    @model_validator(mode="after")
    def validate_thread_id(self):
        if self.type in {"subscribe", "unsubscribe"}:
            if self.thread_id is None:
                raise ValueError("Thread messages require thread_id")
        elif self.thread_id is not None:
            raise ValueError("Control messages do not accept thread_id")
        return self


class UserStatus(BaseModel):
    status: Literal["active", "disabled"]
    role: Literal["member", "moderator", "admin"]


async def load_user_status(user_id: UUID) -> UserStatus:
    redis = get_redis_client()
    key = f"rt:user_status:{user_id}"
    cached = await redis.get(key)
    if cached:
        try:
            return UserStatus.model_validate_json(cached)
        except ValidationError:
            pass
    data = UserStatus.model_validate(await fetch_user_status(str(user_id)))
    await redis.set(key, data.model_dump_json(), ex=get_settings().STATUS_CACHE_TTL_SECONDS)
    return data


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Accept the transport so the first frame can carry authentication.
    await websocket.accept()
    heartbeat_task = None
    disconnect_task = None
    try:
        if websocket.query_params:
            await websocket.close(code=4401)
            return
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT)
            auth = AuthMessage.model_validate_json(raw)
            user = verify_access_token(auth.token)
        except (TimeoutError, ValidationError, HTTPException, KeyError, ValueError):
            await websocket.close(code=4401)
            return
        try:
            status = await load_user_status(user["id"])
        except httpx.HTTPStatusError as exc:
            await websocket.close(code=4401 if exc.response.status_code == 404 else 1011)
            return
        except (httpx.HTTPError, RedisError, ValueError):
            await websocket.close(code=1011)
            return
        if status.status != "active":
            await websocket.close(code=4403, reason="account_disabled")
            return
        if not await manager.connect(websocket, user["id"]):
            await websocket.close(code=4429)
            return
        closed_event = manager.socket_closed[websocket]
        await websocket.send_json({"type": "auth.ok", "user_id": str(user["id"]), "role": status.role})
        last_pong = monotonic()

        async def heartbeat():
            next_ping = monotonic() + HEARTBEAT_INTERVAL
            while True:
                # Wake at the pong deadline even when it falls between pings.
                deadline = min(next_ping, last_pong + PONG_TIMEOUT)
                await asyncio.sleep(max(0, deadline - monotonic()))
                now = monotonic()
                if now - last_pong >= PONG_TIMEOUT:
                    await websocket.close(code=1001, reason="heartbeat_timeout")
                    return
                if now >= next_ping:
                    await websocket.send_json({"type": "ping"})
                    next_ping = now + HEARTBEAT_INTERVAL

        heartbeat_task = asyncio.create_task(heartbeat())
        disconnect_task = asyncio.create_task(closed_event.wait())

        async def receive_or_heartbeat():
            # A server-initiated close must also stop an idle receive operation.
            receive_task = asyncio.create_task(websocket.receive_text())
            try:
                done, _ = await asyncio.wait(
                    {receive_task, heartbeat_task, disconnect_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if disconnect_task in done:
                    return None
                if heartbeat_task in done:
                    heartbeat_task.result()
                    return None
                return receive_task.result()
            finally:
                receive_task.cancel()
                await asyncio.gather(receive_task, return_exceptions=True)

        messages = deque()
        while True:
            try:
                raw = await receive_or_heartbeat()
            except KeyError:
                await websocket.close(code=1008)
                return
            if raw is None:
                return
            now = monotonic()
            while messages and now - messages[0] >= 60:
                messages.popleft()
            if len(messages) >= MESSAGE_LIMIT:
                await websocket.close(code=4429)
                return
            messages.append(now)
            try:
                message = ClientMessage.model_validate_json(raw)
            except ValidationError:
                await websocket.close(code=1008)
                return
            if message.type == "pong":
                last_pong = now
            elif message.type == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.type == "subscribe":
                await manager.subscribe_thread(websocket, message.thread_id)
            else:
                if not await manager.unsubscribe_thread(websocket, message.thread_id):
                    await websocket.send_json({"type": "error", "code": "not_subscribed"})
    except (WebSocketDisconnect, OSError):
        pass
    finally:
        # ASGI shutdown may cancel the session while child tasks are stopping.
        # Always finish room cleanup before leaving the endpoint.
        with CancelScope(shield=True):
            tasks = [task for task in (disconnect_task, heartbeat_task) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await manager.disconnect(websocket)
