import httpx

from app.core.config import get_settings


async def get_user_profiles(user_ids: list[str]) -> dict[str, dict]:
    if not user_ids:
        return {}

    settings = get_settings()
    headers = {"X-Service-Key": settings.IDENTITY_SERVICE_KEY}

    profiles = {}

    async with httpx.AsyncClient(timeout=3.0) as client:
        for user_id in set(user_ids):
            response = await client.get(
                f"{settings.IDENTITY_BASE_URL}/internal/users/{user_id}/status",
                headers=headers,
            )
            response.raise_for_status()

            profile = response.json()
            profiles[str(profile["id"])] = profile

    return profiles