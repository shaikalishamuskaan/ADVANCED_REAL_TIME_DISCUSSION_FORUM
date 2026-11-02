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

# Fresh Clone Setup Guide

This guide explains how to clone and run the **Advanced Real-Time
Discussion Forum** on a new Windows computer using Docker Desktop.

## 1. Prerequisites

Install and start:

-   [Git](https://git-scm.com/downloads)
-   [Docker Desktop](https://www.docker.com/products/docker-desktop/)

You do not need to install Python, Node.js, PostgreSQL, or Redis on the
host computer. The application runs through Docker.

## 2. Clone the repository

Open PowerShell and run:

``` powershell
git clone https://github.com/shaikalishamuskaan/ADVANCED_REAL_TIME_DISCUSSION_FORUM.git
cd ADVANCED_REAL_TIME_DISCUSSION_FORUM
```

## 3. Build the bootstrap image

``` powershell
docker build -t forum-identity:local -f services/identity/Dockerfile .
```

## 4. Generate local environment configuration

``` powershell
docker run --rm --entrypoint python --mount "type=bind,source=$($PWD.Path),target=/workspace" forum-identity:local /workspace/infrastructure/docker/bootstrap.py
```

The bootstrap script prepares the local environment configuration,
credentials, and matching JWT keys.

**Important:** - Keep the generated `.env` and `.env.docker` files
private. - Do not commit generated environment files or secrets. - Do
not overwrite generated configuration with `.env.example`. - Keep the
generated configuration if you restart the same local instance.

## 5. Build and start the application

``` powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml up -d --build --wait
```

Docker Compose builds and starts the application services and waits for
the configured health checks.

## 6. Open the application

Open this address in your browser:

<http://localhost:8080>

## 7. Check service status

``` powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml ps
```

Check that the application services are healthy. Database migration jobs
should have completed successfully.

## 8. Stop the application safely

``` powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml down
```

This stops and removes the containers and network while preserving named
database volumes.

**Do not use `docker compose down -v`** unless you intentionally want to
delete the database volumes and their data.

To start the same local instance again, use Step 5. You do not need to
run the bootstrap command again unless you are preparing a new checkout.

------------------------------------------------------------------------

## Optional: Use alternate ports if the default ports are occupied

If another copy of the project is already using the default host ports,
create a file named `compose.local-ports.yaml` in the project root with
this content:

``` yaml
services:
  frontend:
    ports: !override
      - "18080:8080"
  postgres:
    ports: !override
      - "15433:5432"
  redis:
    ports: !override
      - "16380:6379"
```

This requires a Docker Compose version that supports the `!override` tag
(Docker Compose v2.24.4 or later).

Validate the configuration:

``` powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml -f compose.local-ports.yaml config --quiet
```

Start the application with the alternate ports:

``` powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml -f compose.local-ports.yaml up -d --build --wait
```

Open the application at:

<http://localhost:18080>

For status and shutdown commands, include the same three Compose files:

``` powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml -f compose.local-ports.yaml ps
```

``` powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml -f compose.local-ports.yaml down
```

The alternate-port file is a local override. Do not commit it unless you
intentionally want to make it part of the repository's shared setup.

## Troubleshooting notes

-   Make sure Docker Desktop is running before executing Docker
    commands.
-   Run all commands from the repository root unless a step says
    otherwise.
-   If a port is already allocated, use the alternate-port procedure
    above.
-   If a container is unhealthy, inspect its status with the `ps`
    command and then check the relevant service logs.
-   Do not share `.env`, `.env.docker`, passwords, tokens, private keys,
    or full configuration output when asking for help.

