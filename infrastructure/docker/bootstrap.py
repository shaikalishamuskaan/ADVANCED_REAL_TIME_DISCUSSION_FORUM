"""First-run Docker setup. Generate missing development configuration only."""
import argparse
import importlib.util
import json
import secrets
from pathlib import Path
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ("POSTGRES_USER", "POSTGRES_PASSWORD", "DJANGO_SECRET_KEY", "RECOVERY_CODE_HMAC_KEY", "SERVICE_API_KEYS")


def write_missing(path, values):
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        output.write("# Local development configuration; never commit.\n")
        for name, value in values.items():
            escaped = str(value).replace("'", "\\'")
            output.write(f"{name}='{escaped}'\n")
    path.chmod(0o600)


def bootstrap(root=ROOT):
    env = root / ".env"
    key_dir = root / "services/identity/keys"
    private_path, public_path = key_dir / "jwt-private.pem", key_dir / "jwt-public.pem"
    if not env.exists():
        if private_path.exists() or public_path.exists():
            raise ValueError("Existing JWT keys found without .env. Restore the matching configuration; no files changed.")
        service_keys = {name: secrets.token_urlsafe(32) for name in ("discussion", "notify", "realtime")}
        root_values = {
            "APP_ENV": "development", "LOG_LEVEL": "INFO", "POSTGRES_USER": "forum_dev",
            "POSTGRES_PASSWORD": secrets.token_urlsafe(32), "DJANGO_SECRET_KEY": secrets.token_urlsafe(48),
            "RECOVERY_CODE_HMAC_KEY": secrets.token_urlsafe(48), "SERVICE_API_KEYS": json.dumps(service_keys),
            "SEARCH_SERVICE_KEY": secrets.token_urlsafe(32),
            "JWT_PRIVATE_KEY_PATH": "services/identity/keys/jwt-private.pem",
            "JWT_PUBLIC_KEY_PATH": "services/identity/keys/jwt-public.pem", "JWT_ISSUER": "identity",
            "JWT_AUDIENCE": "forum", "ACCESS_TOKEN_TTL_SECONDS": "900", "REFRESH_TOKEN_TTL_DAYS": "7",
            "REDIS_URL": "redis://localhost:6380/0", "OUTBOX_RELAY_INTERVAL_MS": "200",
            "OUTBOX_BATCH_SIZE": "100", "OUTBOX_RETENTION_DAYS": "7",
        }
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_dir.mkdir(parents=True, exist_ok=True)
        key_dir.chmod(0o700)
        # The directory protects host access. Individual secret mounts must be
        # readable by the application's non-root UID inside Docker.
        with private_path.open("xb") as output:
            output.write(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        with public_path.open("xb") as output:
            output.write(private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        private_path.chmod(0o644)
        public_path.chmod(0o644)
        write_missing(env, root_values)
    source = dotenv_values(env)
    for name in REQUIRED:
        value = source.get(name)
        if not value or "replace_with" in value or "YOUR_LOCAL" in value:
            raise ValueError(f"Configure {name} in the existing .env; existing values were not overwritten")
    if not private_path.is_file() or not public_path.is_file():
        raise ValueError("Existing configuration has missing JWT keys. Restore the original pair; keys were not regenerated.")
    private = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    public = serialization.load_pem_public_key(public_path.read_bytes())
    if not isinstance(private, rsa.RSAPrivateKey) or private.public_key().public_numbers() != public.public_numbers():
        raise ValueError("JWT key pair does not match; existing files were not changed")
    service_keys = json.loads(source["SERVICE_API_KEYS"])
    if set(service_keys) != {"discussion", "notify", "realtime"}:
        raise ValueError("SERVICE_API_KEYS must contain discussion, notify and realtime")
    discussion = dotenv_values(root / "services/discussion/.env")
    search = dotenv_values(root / "services/search/.env")
    export_keys = {value for value in (source.get("SEARCH_SERVICE_KEY"), discussion.get("SEARCH_SERVICE_KEY"), search.get("SEARCH_SERVICE_KEY")) if value}
    if len(export_keys) > 1:
        raise ValueError("Existing Search export keys disagree; configuration was not overwritten")
    export_key = next(iter(export_keys), "")
    for service, database, caller in (("discussion", "discussion_db", "discussion"),
                                      ("notification_realtime", "notification_db", "notify"),
                                      ("search", "search_db", None)):
        values = {"APP_ENV": "development", "DATABASE_URL": "postgresql+asyncpg://{}:{}@localhost:5433/{}".format(
            quote(source["POSTGRES_USER"], safe=""), quote(source["POSTGRES_PASSWORD"], safe=""), database),
            "REDIS_URL": "redis://localhost:6380/0", "JWT_PUBLIC_KEY_PATH": "../identity/keys/jwt-public.pem",
            "JWT_ISSUER": source.get("JWT_ISSUER", "identity"), "JWT_AUDIENCE": source.get("JWT_AUDIENCE", "forum")}
        if caller:
            values.update(IDENTITY_BASE_URL="http://localhost:8000", IDENTITY_SERVICE_KEY=service_keys[caller])
        if service in {"discussion", "search"}:
            values["SEARCH_SERVICE_KEY"] = export_key
        write_missing(root / "services" / service / ".env", values)
    spec = importlib.util.spec_from_file_location("forum_prepare_env", ROOT / "infrastructure/docker/prepare_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.prepare(root)
    print("Development configuration and matching JWT keys are ready. Existing configuration was preserved.")
    print("Prepared Git-ignored .env.docker. No passwords, tokens, recovery codes or key contents were printed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    options = parser.parse_args()
    try:
        bootstrap(options.root.resolve())
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(str(error)) from None
