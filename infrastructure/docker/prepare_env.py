"""Reuse existing local credentials for Compose; never print their values."""
import json
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]
OPTIONAL = ("COMPOSE_PROJECT_NAME", "FRONTEND_HOST_PORT", "POSTGRES_HOST_PORT", "REDIS_HOST_PORT", "POSTGRES_CONTAINER_NAME", "REDIS_CONTAINER_NAME")


def prepare(root=ROOT):
    source = dotenv_values(root / ".env")
    required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "DJANGO_SECRET_KEY", "RECOVERY_CODE_HMAC_KEY", "SERVICE_API_KEYS")
    for name in required:
        if not source.get(name):
            raise ValueError(f"Missing {name} in root .env; existing secrets were not modified")
    service_keys = json.loads(source["SERVICE_API_KEYS"])
    if set(service_keys) != {"discussion", "notify", "realtime"} or not all(service_keys.values()):
        raise ValueError("Identity SERVICE_API_KEYS must define discussion, notify, and realtime")
    for name in ("jwt-private.pem", "jwt-public.pem"):
        if not (root / "services/identity/keys" / name).is_file():
            raise ValueError(f"Missing existing Identity key file: {name}; no keys were generated")
    discussion = dotenv_values(root / "services/discussion/.env")
    search = dotenv_values(root / "services/search/.env")
    export_keys = {value for value in (source.get("SEARCH_SERVICE_KEY"), discussion.get("SEARCH_SERVICE_KEY"), search.get("SEARCH_SERVICE_KEY")) if value}
    export_key = next(iter(export_keys), "")
    if len(export_keys) > 1:
        raise ValueError("Existing Search export keys disagree; resolve their configuration before deployment")
    values = {name: source[name] for name in required}
    values.update({
        "DISCUSSION_SERVICE_KEY": service_keys["discussion"],
        "NOTIFY_SERVICE_KEY": service_keys["notify"],
        "SEARCH_SERVICE_KEY": export_key,
        "JWT_ISSUER": source.get("JWT_ISSUER", "identity"),
        "LOG_LEVEL": source.get("LOG_LEVEL", "INFO"),
        "JWT_AUDIENCE": source.get("JWT_AUDIENCE", "forum"),
        "ACCESS_TOKEN_TTL_SECONDS": source.get("ACCESS_TOKEN_TTL_SECONDS", "900"),
        "REFRESH_TOKEN_TTL_DAYS": source.get("REFRESH_TOKEN_TTL_DAYS", "7"),
    })
    values.update({name: source[name] for name in OPTIONAL if source.get(name)})
    lines = ["# Generated local Docker configuration. Contains existing secrets; do not commit."]
    for name, value in values.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"Unsupported multiline value for {name}")
        escaped = value.replace("'", "\\'")
        lines.append(f"{name}='{escaped}'")
    destination = root / ".env.docker"
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    destination.chmod(0o600)
    return destination


if __name__ == "__main__":
    try:
        prepare()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from None
    print("Prepared Git-ignored .env.docker from existing credentials. No secrets or keys changed.")
