"""Reuse existing local credentials for Compose; never print their values."""
import json
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]
source = dotenv_values(ROOT / ".env")
required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "DJANGO_SECRET_KEY", "RECOVERY_CODE_HMAC_KEY", "SERVICE_API_KEYS")
for name in required:
    if not source.get(name):
        raise SystemExit(f"Missing {name} in root .env; existing secrets were not modified")
service_keys = json.loads(source["SERVICE_API_KEYS"])
if set(service_keys) != {"discussion", "notify", "realtime"} or not all(service_keys.values()):
    raise SystemExit("Identity SERVICE_API_KEYS must define discussion, notify, and realtime")
for name in ("jwt-private.pem", "jwt-public.pem"):
    if not (ROOT / "services/identity/keys" / name).is_file():
        raise SystemExit(f"Missing existing Identity key file: {name}; no keys were generated")
discussion = dotenv_values(ROOT / "services/discussion/.env")
search = dotenv_values(ROOT / "services/search/.env")
export_key = discussion.get("SEARCH_SERVICE_KEY") or search.get("SEARCH_SERVICE_KEY") or ""
if discussion.get("SEARCH_SERVICE_KEY") and search.get("SEARCH_SERVICE_KEY") and discussion["SEARCH_SERVICE_KEY"] != search["SEARCH_SERVICE_KEY"]:
    raise SystemExit("Existing Search export keys disagree; resolve their configuration before deployment")
values = {name: source[name] for name in required}
values.update({
    "DISCUSSION_SERVICE_KEY": service_keys["discussion"],
    "NOTIFY_SERVICE_KEY": service_keys["notify"],
    "SEARCH_SERVICE_KEY": export_key,
    "JWT_ISSUER": source.get("JWT_ISSUER", "identity"),
    "JWT_AUDIENCE": source.get("JWT_AUDIENCE", "forum"),
    "ACCESS_TOKEN_TTL_SECONDS": source.get("ACCESS_TOKEN_TTL_SECONDS", "900"),
    "REFRESH_TOKEN_TTL_DAYS": source.get("REFRESH_TOKEN_TTL_DAYS", "7"),
})
lines = ["# Generated local Docker configuration. Contains existing secrets; do not commit."]
for name, value in values.items():
    if "\n" in value or "\r" in value:
        raise SystemExit(f"Unsupported multiline value for {name}")
    escaped = value.replace("'", "\\'")
    lines.append(f"{name}='{escaped}'")
destination = ROOT / ".env.docker"
destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("Prepared Git-ignored .env.docker from existing credentials. No secrets or keys changed.")
if not export_key:
    print("Search rebuild export key is unset; live Search works, but rebuild requires an existing configured key.")
