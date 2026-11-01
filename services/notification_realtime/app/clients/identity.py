from collections import OrderedDict
from time import monotonic
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, TypeAdapter

from app.core.config import get_settings

USERNAME_CACHE_TTL_SECONDS = 60
USERNAME_CACHE_MAX_ENTRIES = 1024
_username_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()


class ResolvedUser(BaseModel):
    id: UUID
    username: str = Field(pattern=r"^[A-Za-z0-9_]{3,30}$")


resolved_users_adapter = TypeAdapter(list[ResolvedUser])


async def resolve_usernames(usernames: list[str]) -> dict[str, dict]:
    if not usernames:
        return {}

    now = monotonic()
    for name, (expires_at, _) in list(_username_cache.items()):
        if now >= expires_at:
            _username_cache.pop(name)

    requested = {}
    for name in usernames:
        requested.setdefault(name.lower(), name)
    resolved = {}
    missing = []
    for normalized, original in requested.items():
        cached = _username_cache.get(normalized)
        if cached is None:
            missing.append(original)
        else:
            _username_cache.move_to_end(normalized)
            resolved[normalized] = cached[1].copy()
    if not missing:
        return resolved

    settings = get_settings()

    headers = {
        "X-Service-Key": settings.IDENTITY_SERVICE_KEY,
    }

    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.post(
            f"{settings.IDENTITY_BASE_URL}/internal/users/resolve",
            json={"usernames": missing},
            headers=headers,
        )
        response.raise_for_status()

    # Validate the whole response before storing anything. Failed lookups must
    # remain retryable rather than turning into cached missing users.
    users = resolved_users_adapter.validate_python(response.json())
    expires_at = monotonic() + USERNAME_CACHE_TTL_SECONDS
    missing_names = {name.lower() for name in missing}
    for user in users:
        normalized = user.username.lower()
        if normalized not in missing_names:
            continue
        record = user.model_dump(mode="json")
        _username_cache[normalized] = (expires_at, record)
        _username_cache.move_to_end(normalized)
        resolved[normalized] = record.copy()
        while len(_username_cache) > USERNAME_CACHE_MAX_ENTRIES:
            _username_cache.popitem(last=False)

    # Unknown names are omitted and looked up again on a later event, so newly
    # registered or renamed accounts are not hidden by a negative cache entry.
    return resolved


async def fetch_user_status(user_id: str) -> dict:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.get(
            f"{settings.IDENTITY_BASE_URL}/internal/users/{user_id}/status",
            headers={"X-Service-Key": settings.IDENTITY_SERVICE_KEY},
        )
        response.raise_for_status()
        return response.json()
