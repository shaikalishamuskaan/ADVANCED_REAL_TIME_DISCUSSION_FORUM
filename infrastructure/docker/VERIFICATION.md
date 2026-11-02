# Fresh-clone verification

Verified on 2 November 2026 using Windows PowerShell and Docker Desktop's Linux
containers. Linux/macOS commands are documented in the repository README; those
host platforms were not separately exercised in this audit.

An isolated Git clone was created from committed source. Before setup it contained
no `.env`, JWT key pair, virtual environment or frontend node_modules. It did not
use the original application's accounts, database volumes or Redis data.

## Startup checks

- Built Identity from tracked files and pinned Python dependencies.
- Ran the README's Docker-only bootstrap, with no host Python/Node/OpenSSL setup.
- Repeated bootstrap: generated configuration/key values were preserved.
- Used separate container names, project/network, volumes and host ports.
- Built all application images; frontend TypeScript/Vite production build passed.
- Started PostgreSQL and Redis with empty volumes and initialized all databases.
- All four Django/Alembic migration jobs completed successfully.
- All API/frontend health checks passed and both Identity workers stayed running.
- Verified generated credentials and keys remain Git-ignored.

## Functional checks against the fresh databases

- Identity's application database initially contained zero users.
- Created the first administrator through Django's existing createsuperuser
  management command, without modifying authentication or constructing hashes.
- Registered two members and signed in through the gateway.
- Created a thread, a comment and a like.
- Two independent authenticated WebSocket connections received the same live
  like/comment publications.
- A mention produced the expected notification, and Search indexed the content.
- Administrator user management changed a member to moderator.
- After the normal service permission-cache delay, the moderator resolved a
  report and received the corresponding forum activity record.
- Verification sessions were logged out. Credentials, recovery codes and tokens
  were not printed.

## Automated checks and observations

The clean-clone containers passed 186 Discussion, 190 Notification & Realtime and
101 Search tests, including their opt-in integration checks. Six bootstrap tests
and all 81 frontend DOM tests passed inside Docker, with no host Node installation
in the clone. The final suite totals are 711 passing tests (including Identity and
the shared logging tests below).

The first Identity suite run had one intermittent 401 in the role-change test.
The targeted six-test role suite and the subsequent full 136-test Identity run
passed. Safe JWT diagnostics did not reproduce the failure. Authentication
verification was not relaxed, and no test was skipped or weakened to hide it.
The fresh-database login, admin and moderation functional checks also passed.

The audit found and fixed the standalone shared-test import path by setting
`PYTHONPATH=/app` in Python images. All 11 shared logging tests passed using the
documented command after that fix. All three generated audit accounts and their
roles persisted across the documented rebuild. Both the isolated frontend and
the original application remained reachable on their separate ports.

These checks validate the documented local setup under the prerequisites in the
README. They do not guarantee uninterrupted operation on every OS, future Docker
release, network connection, or machine clock, and do not constitute public
production deployment or rendered browser/device testing.
