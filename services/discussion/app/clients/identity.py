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
            response = await client.get(url, headers=headers)

        if response.status_code == 404:
            raise ValueError("User does not exist in Identity.")

        response.raise_for_status()
        data = response.json()

        required_fields = {"id", "username", "role", "status"}
        if not required_fields.issubset(data):
            raise RuntimeError("Incomplete Identity status response.")

        return data

    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            "Identity Service returned an unsuccessful response."
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError("Identity Service is unavailable.") from exc


async def fetch_user_profiles(user_ids: list[str]) -> list[dict]:
    """Fetch public author profiles from Identity's batch endpoint."""
    if not user_ids:
        return []

    settings = get_settings()

    url = f"{settings.IDENTITY_BASE_URL}/internal/users/batch"
    headers = {
        "X-Service-Key": settings.IDENTITY_SERVICE_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json={"ids": user_ids},
            )

        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict) or not isinstance(
            data.get("items"), list
        ):
            raise RuntimeError("Invalid Identity batch response.")

        required_fields = {
            "id",
            "username",
            "display_name",
            "avatar_url",
        }

        for item in data["items"]:
            if not required_fields.issubset(item):
                raise RuntimeError(
                    "Identity returned an incomplete author profile."
                )

        return data["items"]

    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            "Identity batch lookup returned an unsuccessful response."
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(
            "Identity batch lookup is unavailable."
        ) from exc