import httpx

from app.core.config import get_settings


async def fetch_user_status(user_id: str) -> dict:
    settings = get_settings()

    url = (
        f"{settings.IDENTITY_BASE_URL}"
        f"/internal/users/{user_id}/status"
    )

    headers = {
        "X-Service-Key": settings.IDENTITY_SERVICE_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.get(
                url,
                headers=headers,
            )

        if response.status_code == 404:
            raise ValueError("User does not exist in Identity.")

        response.raise_for_status()

        data = response.json()

        required_fields = {"id", "username", "role", "status"}

        if not required_fields.issubset(data):
            raise RuntimeError(
                "Identity returned an incomplete user status response."
            )

        return data

    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            "Identity Service returned an unsuccessful response."
        ) from exc

    except httpx.RequestError as exc:
        raise RuntimeError(
            "Identity Service is unavailable."
        ) from exc