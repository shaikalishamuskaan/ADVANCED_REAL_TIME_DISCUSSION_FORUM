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
- Docker Desktop with **Linux containers**, or Docker Engine with Docker Compose 2.20+.
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

Each new bootstrap saves a unique `COMPOSE_PROJECT_NAME` in `.env` and
`.env.docker`. Compose uses it for this checkout's network, containers and volumes.
Two folders with the same repository name therefore do not accidentally share a
database. Keep using `--env-file .env.docker` on every Compose command. Do not
change the saved project name to connect an existing instance to different data.
Bootstrap creates service configuration automatically; you do not need to edit
individual service `.env` files for Docker.

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
Service permission caches normally expire within 30 seconds, so a role change
can take a short time to appear across services.

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
test summary determines success. The frontend production build checks TypeScript.
To run frontend DOM tests without installing Node on your computer:

```text
docker build --target build -t forum-frontend-tests:local -f frontend/Dockerfile .
docker run --rm forum-frontend-tests:local npm test
```

To check bootstrap's configuration generation and preservation without host Python
(PowerShell, from the repository root):

```powershell
docker run --rm --entrypoint python --mount "type=bind,source=$($PWD.Path),target=/workspace" forum-identity:local -m unittest discover -s /workspace/infrastructure/docker/tests -v
```

Alternatively, developers with host Node.js 22.12+ can run `npm.cmd ci` and
`npm.cmd test` from `frontend`.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Cannot connect to Docker | Start Docker Desktop and select Linux containers |
| Missing `.env.docker` | Run the bootstrap command from the repository root |
| A port/container name is already allocated | Stop the conflicting local stack, or use the custom settings below |
| Images cannot download | Check Internet access, proxy settings and Docker registry access; retry the build |
| Existing configuration has missing/mismatched keys | Restore the matching key pair; setup deliberately does not rotate existing keys |
| PostgreSQL is unhealthy / database credential check failed | Its TCP password check failed. An existing volume retains its original password even when the container environment changes. Restore the matching configuration; see below. |
| UI is reachable but API calls fail | Check `ps -a` and logs for the relevant service and migration job |
| Changes do not appear | Rebuild containers after pulling/editing source, then reload the page |
| Session/refresh fails | Use the same localhost URL consistently; inspect Origin/proxy settings and Identity logs |

### Existing database password mismatch

PostgreSQL initialization runs only when its data volume is empty. Changing
`POSTGRES_PASSWORD` in a container does **not** change an existing database user's
password. Earlier versions used the repository folder name as the Compose project
and fixed container names. A second clone with the same folder name could reuse
the original volume while bootstrap generated a new password. All migration jobs
then failed, although `pg_isready` reported healthy. The health check now executes
an authenticated SQL query over the container network before migrations start.

To recover existing data, restore the original matching `.env` and JWT keys from
your own backup, rerun bootstrap to regenerate `.env.docker`, and start the same
Compose project. Existing configuration without a saved project name keeps the
existing project/volume selection so bootstrap does not silently abandon its data.
Do not paste passwords in commands, change a database password blindly, or use
`docker compose down -v` to resolve this error. If the original configuration is
unavailable, keep the volume and arrange a database recovery separately.

### Second instance or clean development reset, preserving existing data

A safe fresh start uses a **new checkout with new volumes**, leaving the original
checkout, configuration and database volumes intact. If you only need to restart
or update, use the everyday commands above instead.

In a parent directory, run the following PowerShell commands. The explicit ports
allow this instance to run alongside the first one; choose other unused ports if
these are occupied. These bootstrap options apply only before `.env` exists:

```powershell
git clone https://github.com/shaikalishamuskaan/ADVANCED_REAL_TIME_DISCUSSION_FORUM.git forum-fresh
cd forum-fresh
docker build -t forum-identity:local -f services/identity/Dockerfile .
docker run --rm --entrypoint python --mount "type=bind,source=$($PWD.Path),target=/workspace" forum-identity:local /workspace/infrastructure/docker/bootstrap.py --frontend-port 18080 --postgres-port 15433 --redis-port 16380
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml up -d --build --wait
```

Open **http://localhost:18080** and register a new account. The saved random project
name isolates this installation automatically; no additional `-p` is necessary.
Switch back by stopping this stack, returning to the original checkout, and
starting its stack. Nothing above deletes data. Do not remove volumes until you
have explicitly identified them, backed up the data, and decided to discard it.
Avoid global Docker prune commands during evaluation.

## Repository and security notes

Clean-install verification on 2 November 2026 used a separate source-only checkout,
fresh generated secrets/keys, a separate Compose project and unused host ports.
All four migration jobs exited 0; PostgreSQL, Redis, four APIs and frontend became
healthy. Registration/login, authenticated profile access, thread creation/read,
notifications access, authenticated WebSocket subscription and live comment
delivery, and event-driven Search indexing passed through the frontend gateway.
Identity's unauthenticated health probe expects HTTP 401; authenticated profile
access returned 200. The other API health probes and frontend health returned 200.
Rerunning bootstrap and stopping/starting the stack preserved its configuration,
accounts and discussion records. Existing installations' volumes were untouched.

Automated results: Identity **136**, Discussion **186**, Notification & Realtime
**190**, Search **101**, shared logging **11**, bootstrap **9**, and frontend
**81** tests passed (**714 total**, none skipped). TypeScript and the frontend
production build passed. Notification tests emit one upstream Starlette/httpx
deprecation warning. These checks cover real HTTP/WebSocket traffic and frontend
DOM tests; a rendered browser walkthrough remains a useful final manual check.

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
[fresh-clone verification](infrastructure/docker/VERIFICATION.md),
[Identity tests](services/identity/tests/README.md), [logging](forum_logging/README.md),
[LLD](low-level-design.md), [HLD](<01-high-level-design .md>), and
[product requirements](requiments.txt).
