# Advanced Real-Time Discussion Forum

A discussion forum with registration/login, nested replies, likes, keyword search,
reply/mention notifications, moderator tools, administrator tools, and live updates.
The React frontend talks to four independently running Python services through
one gateway.

| Component | Responsibility |
| --- | --- |
| Identity: Django + Django REST Framework | Accounts, RS256 JWT authentication, profiles, roles, recovery and activity logs |
| Discussion: FastAPI | Threads, nested comments, likes, reports and moderation |
| Notification & Realtime: FastAPI | Notifications and authenticated WebSocket connections |
| Search: FastAPI | Event-driven search index and keyword/type/tag search |
| Frontend: React + TypeScript | Member, moderator and administrator screens |
| Nginx | Serves the compiled frontend and routes REST/WebSocket traffic |
| PostgreSQL | A separate database for each backend service |
| Redis | Caching, rate limiting, durable event streams and live Pub/Sub |

## Requirements

- Git.
- Docker Desktop with **Linux containers**, or Docker Engine with Docker Compose v2+.
- Docker must be running. On Windows, use Docker Desktop's WSL 2 backend.
- Internet access for the first image/dependency download and enough disk space
  for the images and database volumes. Allow roughly 4 GB of available memory.

**The Docker quick start needs no host Python, virtual environment, Node.js,
PostgreSQL, Redis, OpenSSL, or manually copied secret files.** Python and Node
dependencies are installed during image builds. Python containers use tested
`requirements.lock.txt` files; the frontend uses `package-lock.json` and `npm ci`.

## First run after cloning

### Windows PowerShell

Run these commands in order:

```powershell
git clone https://github.com/shaikalishamuskaan/ADVANCED_REAL_TIME_DISCUSSION_FORUM.git
cd ADVANCED_REAL_TIME_DISCUSSION_FORUM

docker build -t forum-identity:local -f services/identity/Dockerfile .
docker run --rm --entrypoint python --mount "type=bind,source=$($PWD.Path),target=/workspace" forum-identity:local /workspace/infrastructure/docker/bootstrap.py

docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml up -d --build --wait
```

### Linux / macOS terminal

```bash
git clone https://github.com/shaikalishamuskaan/ADVANCED_REAL_TIME_DISCUSSION_FORUM.git
cd ADVANCED_REAL_TIME_DISCUSSION_FORUM

docker build -t forum-identity:local -f services/identity/Dockerfile .
docker run --rm --user "$(id -u):$(id -g)" --entrypoint python --mount "type=bind,source=$(pwd),target=/workspace" forum-identity:local /workspace/infrastructure/docker/bootstrap.py

docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml up -d --build --wait
```

The user flag on Linux/macOS makes generated files belong to your host user.
Run from the cloned repository root; do not run the setup commands from `frontend`.

Open **http://localhost:8080** when Compose finishes.

The bootstrap command generates unique, development-only database credentials,
application secrets, service keys, a matching RSA JWT key pair, and the required
local environment files. It does not print these values or create default users.
Repeated setup preserves existing settings and keys. Do not copy `.env.example`
over a generated `.env`: the example contains placeholders, not working secrets.

Compose initializes all four databases and runs Django/Alembic migrations before
starting the APIs. Four migration containers showing **Exited (0)** are expected.

## Create your accounts

A fresh clone starts with an empty database. Your previous computer's accounts,
passwords and discussions are not included in Git.

1. Open the application and choose **Create an account** to create a member.
2. Save the one-time recovery code when the application displays it.
3. Sign in using the **email address and password** you registered.

To create the first administrator, run this interactive command from the project
root. It prompts for email, username, display name and password; Django hashes the
password using the existing application configuration:

```text
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml exec identity python manage.py createsuperuser
```

Sign in through the same frontend using the administrator's email. To create a
moderator, register another member, then use **Members -> Manage -> Role** while
signed in as administrator. Supported roles are `member`, `moderator`, and `admin`.
Do not change account roles through raw SQL.

## Everyday use

Open Docker Desktop, then run from the repository root:

```text
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml up -d --wait
```

Open **http://localhost:8080**. No separate backend terminals or `npm run dev:all`
are needed when using Docker.

After pulling source updates, rebuild to include the changed files:

```text
git pull
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml up -d --build --wait
```

Stop the stack without deleting accounts/content:

```text
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml stop
```

PostgreSQL and Redis data live in named Docker volumes. Keep those volumes and
your generated secrets when restarting/updating. Moving existing content to a
different computer requires a database backup/restore and matching configuration;
cloning source alone does not transfer it. Volume deletion is not a reset step
in this guide.

## Check startup and logs

```text
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml ps -a
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml logs -f --tail 50
```

API/frontend containers should be healthy. Identity audit/outbox workers should
be running. The relay may stand by while another local relay owns its advisory
lock; only one publishes at a time. Ctrl+C stops log viewing, not the containers.
See the [logging guide](forum_logging/README.md) for JSON logs, request IDs and
bounded log retention. Operational logs are separate from the Activity Log page.

## Tests

These commands run inside Docker, using test databases and isolated integration
fixtures rather than modifying registered application accounts:

```text
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml exec -T identity python manage.py test --keepdb --noinput
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml exec -T -e RUN_DISCUSSION_INTEGRATION=1 discussion python /app/docker/runtime.py python -m pytest tests -q -p no:cacheprovider
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml exec -T -e RUN_OUTBOX_INTEGRATION=1 -e RUN_REDIS_INTEGRATION=1 notification-realtime python /app/docker/runtime.py python -m pytest tests -q -p no:cacheprovider
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml exec -T -e RUN_SEARCH_INTEGRATION=1 search python /app/docker/runtime.py python -m pytest tests -q -p no:cacheprovider
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml exec -T identity python -m unittest discover -s /app/forum_logging/tests -v
```

Some tests deliberately log simulated Redis failures/outbox alerts. The final
test summary determines success. The frontend production build checks TypeScript;
frontend DOM tests can be run using `npm.cmd ci` and `npm.cmd test` from `frontend`
with a compatible host Node.js version (22.12+).

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Cannot connect to Docker | Start Docker Desktop and select Linux containers |
| Missing `.env.docker` | Run the bootstrap command from the repository root |
| A port/container name is already allocated | Stop the conflicting local stack, or use the custom settings below |
| Images cannot download | Check Internet access, proxy settings and Docker registry access; retry the build |
| Existing configuration has missing/mismatched keys | Restore the matching key pair; setup deliberately does not rotate existing keys |
| Database authentication fails with old volumes | Restore the `.env` credentials used to initialize those volumes; do not generate new passwords for an existing database |
| UI is reachable but API calls fail | Check `ps -a` and logs for the relevant service and migration job |
| Changes do not appear | Rebuild containers after pulling/editing source, then reload the page |
| Session/refresh fails | Use the same localhost URL consistently; inspect Origin/proxy settings and Identity logs |

For a second checkout on the same machine, append non-secret overrides to its
generated root `.env`, for example:

```dotenv
FRONTEND_HOST_PORT=18080
POSTGRES_HOST_PORT=15433
REDIS_HOST_PORT=16380
POSTGRES_CONTAINER_NAME=forum-second-postgres
REDIS_CONTAINER_NAME=forum-second-redis
```

Run bootstrap again, then add `-p forum-second` to **every** Compose command for
that checkout (immediately after `docker compose`). Open localhost:18080. This
keeps names, ports, networks and volumes separate from the original stack.

## Repository and security notes

- `.env*`, `.env.dev-accounts`, JWT keys, virtual environments, node_modules,
  generated builds and databases are intentionally excluded from Git.
- Only `.env.example` files contain configuration examples. Do not commit real
  credentials, copy someone else's JWT private key, or share `.env.docker` output.
- JWT keys are mounted read-only at runtime; they are not embedded in images.
- Dependency locks capture the tested Python 3.13 Linux environments. Update locks
  alongside requirements and rerun service/integration tests when upgrading.
- This setup serves **local development over HTTP on localhost**. Public hosting
  needs HTTPS, deployment-specific origins/hosts, protected infrastructure,
  backups and production secret management. Cookie security is not weakened.
- No software setup can guarantee uninterrupted operation on every computer or
  future dependency/OS version. The documented path is validated with a separate
  checkout and fresh configuration; Docker availability and first-build downloads
  remain prerequisites.

Further documentation: [Docker operations](infrastructure/docker/README.md),
[Identity tests](services/identity/tests/README.md), [logging](forum_logging/README.md),
[LLD](low-level-design.md), [HLD](<01-high-level-design .md>), and
[product requirements](requiments.txt).
