import asyncio
import json
import logging
from collections import defaultdict
from uuid import UUID

from fastapi import WebSocket

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # user_id -> set of connected WebSocket objects
        self.user_connections: dict[UUID, set[WebSocket]] = defaultdict(set)

        # Redis channel -> connected WebSocket objects
        self.rooms: dict[str, set[WebSocket]] = defaultdict(set)

        # WebSocket -> authenticated user ID
        self.socket_users: dict[WebSocket, UUID] = {}

        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: UUID) -> bool:
        """Register a socket if the user has not exceeded the connection limit."""
        settings = get_settings()

        async with self.lock:
            connections = self.user_connections[user_id]

            if len(connections) >= settings.WS_MAX_SOCKETS_PER_USER:
                return False

            await websocket.accept()

            connections.add(websocket)
            self.socket_users[websocket] = user_id

            # Every authenticated socket joins these two rooms.
            self.rooms["ws:global"].add(websocket)
            self.rooms[f"ws:user:{user_id}"].add(websocket)

            return True

    async def subscribe_thread(
        self,
        websocket: WebSocket,
        thread_id: UUID,
    ):
        """Subscribe an authenticated socket to a thread."""
        if websocket not in self.socket_users:
            return

        channel = f"ws:thread:{thread_id}"

        async with self.lock:
            self.rooms[channel].add(websocket)

    async def unsubscribe_thread(
        self,
        websocket: WebSocket,
        thread_id: UUID,
    ):
        channel = f"ws:thread:{thread_id}"

        async with self.lock:
            self.rooms[channel].discard(websocket)

            if not self.rooms[channel]:
                self.rooms.pop(channel, None)

    async def disconnect(self, websocket: WebSocket):
        """Remove a socket from every room and its user's connection set."""
        async with self.lock:
            user_id = self.socket_users.pop(websocket, None)

            if user_id is not None:
                connections = self.user_connections.get(user_id)

                if connections:
                    connections.discard(websocket)

                    if not connections:
                        self.user_connections.pop(user_id, None)

            empty_rooms = []

            for channel, sockets in self.rooms.items():
                sockets.discard(websocket)

                if not sockets:
                    empty_rooms.append(channel)

            for channel in empty_rooms:
                self.rooms.pop(channel, None)

    async def publish_to_room(self, channel: str, message: dict):
        """Send a Redis Pub/Sub message to all sockets in the matching room."""
        async with self.lock:
            sockets = list(self.rooms.get(channel, set()))

        if not sockets:
            return

        payload = json.dumps(message, default=str)

        results = await asyncio.gather(
            *(socket.send_text(payload) for socket in sockets),
            return_exceptions=True,
        )

        for socket, result in zip(sockets, results):
            if isinstance(result, Exception):
                logger.warning("WebSocket delivery failed: %s", result)
                await self.disconnect(socket)

    async def connection_count(self, user_id: UUID) -> int:
        async with self.lock:
            return len(self.user_connections.get(user_id, set()))


manager = ConnectionManager()