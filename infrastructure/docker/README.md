# Run the forum in Docker

This starts the application locally in Docker Desktop. Open **http://localhost:8080**.
Your existing development accounts and content remain in the existing PostgreSQL
volume. This setup is for local development/testing, not a public Internet deployment.

## Start

For a **fresh clone with no local configuration or Python environment**, use the
[repository quick start](../../README.md#first-run-after-cloning). It runs first-run
setup inside the Identity image and generates matching development secrets/keys.
The preparation command below is for an already configured host checkout.

Run from the repository root with Docker Desktop running:

```powershell
.\.venv\Scripts\python.exe infrastructure/docker/prepare_env.py
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml up -d --build --wait
```

The preparation script uses the root virtual environment's existing `python-dotenv`
dependency. It copies existing development credentials into Git-ignored `.env.docker`
without printing them or generating replacement secrets. Run it again after changing
the source credentials. Keep `.env.docker` private, just like `.env`.

The first image build downloads dependencies and takes longer. Later builds reuse
Docker's build cache. You do not need `npm run dev:all` for the containerized frontend.
If you stop the host development launcher, its workers are no longer duplicated;
the Docker stack has its own API processes and Identity workers.

## Containers and connections

| Service | Purpose | Docker address |
| --- | --- | --- |
| `frontend` | Compiled React application and Nginx REST/WebSocket gateway | localhost:8080 |
| `identity` | Django ASGI account/auth/admin APIs | identity:8000 |
| `identity-outbox` | Publish Identity events | Background worker |
| `identity-audit` | Consume Discussion audit events | Background worker |
| `discussion` | Threads, replies, likes, reports, and Discussion event relay | discussion:8001 |
| `notification-realtime` | Notifications, WebSockets, event consumers and cleanup | notification-realtime:8002 |
| `search` | Search API and indexing consumers | search:8003 |
| `postgres` | Existing persistent databases | postgres:5432; host port 5433 |
| `redis` | Existing persistent streams, caches and Pub/Sub | redis:6379; host port 6380 |

Four migration containers run before the corresponding APIs start. Successful
migration containers appear as **Exited (0)**; this is expected. APIs have HTTP
health checks. Identity workers run separate foreground management commands with
automatic process restart. PostgreSQL/Redis are reused from `compose.yaml`, with
their existing named volumes. Application services are added by `compose.apps.yaml`.

The containerized Identity relay uses `--wait-for-lock`: if a host development
relay already owns leadership, the container remains running in standby and
takes over when that relay releases its lock. It does not publish concurrently.
The management command's default behavior remains unchanged without this flag.

Only the frontend gateway publishes a new host port, bound to 127.0.0.1. Backend
APIs communicate on the Docker network, so existing host servers on 8000-8003 do
not cause port conflicts. Use the gateway at 8080 when testing this Docker stack.

## Security and configuration

- The Docker build context excludes `.env*`, private/public key files, virtual
  environments, dependency directories, caches, and Git metadata.
- Existing JWT keys are mounted read-only as Compose secrets. Only Identity and
  its workers receive the private key; other services receive the public key.
- Service credentials are supplied at runtime and never embedded in images or
  frontend JavaScript. Each backend gets only its required runtime settings.
- Identity uses `DJANGO_DEBUG=false` and allows Docker's internal `identity`
  hostname. Database host/port overrides leave host-development defaults unchanged.
- Access/refresh authentication and secure-cookie attributes are unchanged.
  The local gateway uses HTTP on localhost. A public deployment needs HTTPS,
  appropriate origins/hosts, and production infrastructure configuration.
- The gateway preserves the browser's Origin for refresh checks, proxies `/ws`,
  and serves `index.html` for React routes such as `/activity` and `/discussions`.
  Docker DNS is resolved at runtime so replacing an API container does not leave
  the gateway pointing permanently at its old address.
- Local Search rebuilds use the existing Discussion export key where configured.
  The preparation script rejects conflicting existing export keys.

Compose waits for health checks and completed migration jobs using its
[documented dependency conditions](https://docs.docker.com/compose/how-tos/startup-order/).

## Inspect and update

For structured request/worker logs, request-ID tracing, log levels and rotation,
see the [logging guide](../../forum_logging/README.md).

```powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml ps -a
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml logs --tail 50 identity discussion notification-realtime search
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml logs --tail 50 identity-audit identity-outbox
```

After changing source code, rebuild and replace application containers:

```powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml up -d --build --wait
```

Images contain a source snapshot; restarting alone does not copy newer host files.
`compose ... config --quiet` validates configuration without displaying secrets.
Avoid sharing unredacted Compose configuration or container environment output.

To stop application containers while leaving the existing database/Redis running:

```powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml stop frontend identity identity-audit identity-outbox discussion notification-realtime search
```

This does not remove data or volumes. Database deletion is not part of startup,
update, or cleanup.

## Tests

Identity's Django tests are included in its image. They use the separate test
database and the existing Django test runner:

```powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml exec identity python manage.py test --keepdb --noinput
```

The frontend image runs TypeScript and Vite's production build during its build.
For backend integration tests, enable the existing opt-in environment flags only
when you intend to run those tests against the configured local infrastructure.
Frontend DOM tests continue to run with `npm.cmd test` from `frontend`.

For example, run Search's complete suite inside its container:

```powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml exec -T -e RUN_SEARCH_INTEGRATION=1 search python /app/docker/runtime.py python -m pytest tests -q -p no:cacheprovider
```

Use `/app/docker/runtime.py` when starting additional SQLAlchemy commands with
`exec`: it constructs that process's database URL from the runtime PostgreSQL
settings, including safe escaping of credentials. Identity reads these settings
directly and does not need this wrapper for management commands.

## Deployment verification

The initial deployment images passed **134 Identity**, **185 Discussion**, **189 Notification
& Realtime**, and **100 Search** tests inside Docker, including opt-in integration
checks. The frontend production build passed inside its Node build stage.
For subsequent logging changes and their expanded test counts, see the logging
guide linked above.

HTTP checks through port 8080 verified existing moderator/admin sign-in, refresh,
profiles, role restrictions, activity, discussions, notifications, unread counts,
and search. WebSocket authentication and heartbeat also passed through Nginx.
Verification sessions were logged out afterward. Browser visual/device checks
remain manual. The original PostgreSQL/Redis containers and volumes were preserved.
