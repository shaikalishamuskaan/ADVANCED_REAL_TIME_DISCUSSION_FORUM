import httpx

from app.core.config import get_settings


async def resolve_usernames(usernames: list[str]) -> dict[str, dict]:
    if not usernames:
        return {}

    settings = get_settings()

    headers = {
        "X-Service-Key": settings.IDENTITY_SERVICE_KEY,
    }

    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.post(
            f"{settings.IDENTITY_BASE_URL}/internal/users/resolve",
            json={"usernames": usernames},
            headers=headers,
        )
        response.raise_for_status()

    users = response.json()

    # Identity returns matching user records containing id and username.
    return {
        user["username"].lower(): user
        for user in users
    }