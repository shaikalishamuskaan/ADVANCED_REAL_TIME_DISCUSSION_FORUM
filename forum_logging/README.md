# Application logging

The four Python services share this standard-library logging package. Each
service still starts independently; a small bootstrap locates the repository
root for host execution, and Docker images copy the same package into `/app`.

Application log records are JSON written to stdout. Existing Django management
command progress messages and migration tooling may still output plain text.
These operational logs are separate from the database-backed Activity Log.
The Activity page and its role permissions are unchanged.

## Read logs

From the repository root:

```powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml logs -f --tail 50 identity discussion notification-realtime search frontend
```

For workers:

```powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml logs -f --tail 50 identity-audit identity-outbox
```

Press Ctrl+C to stop following logs; this does not stop the containers.

## What a record means

```json
{"timestamp":"2026-11-02T00:00:00+00:00","level":"INFO","service":"discussion","logger":"forum.requests","event":"http.request","request_id":"11111111222243338444555555555555","method":"GET","route":"/api/forum/threads","status":200,"duration_ms":8.5}
```

- `timestamp`: UTC time, independent of the host's timezone.
- `service`: the backend that produced the record.
- `event`: request completion, worker processing, or another diagnostic message.
- `request_id`: connects a gateway request to backend and internal HTTP calls.
- `route`: the route template, without query parameters or concrete user IDs.
- `status`: HTTP response code; 4xx are rejected requests, 5xx are server errors.
- `duration_ms`: elapsed request time in Python services. Gateway records use
  `duration_seconds` instead, matching Nginx's native timing.

Nginx generates a new request ID and returns it in `X-Request-ID`. You can find
it in your browser's Network response headers, then search logs for that value:

```powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml logs --since 10m | Select-String 'PASTE_REQUEST_ID_HERE'
```

Direct backend requests can supply a valid UUID in `X-Request-ID`; invalid values
are replaced. Request IDs are diagnostic identifiers, never credentials.
Inter-service Identity lookups forward the same ID. Durable stream workers use
their existing event/message IDs instead; event envelopes were not changed.

WebSockets log connection completion, duration, acceptance and close code, not
individual messages. Successful health requests also produce request records;
Identity's internal health probe deliberately receives 401 without credentials.
Use the `route` and `status` fields when filtering this expected traffic.

## Privacy and log levels

Request logging does not read or record request/response bodies, query strings,
authorization headers, cookies, passwords, recovery codes, or service keys.
Unknown route paths are represented as `<unmatched>`. Exceptions include their
type and stack file/function/line locations, without exception messages, source
lines, SQL parameters or local variables that could contain sensitive values.

HTTP-client, SQL and WebSocket frame debug tracing stays disabled even when
application `LOG_LEVEL=DEBUG`. Nginx access logs omit URLs and query strings;
routine raw-URL error logging is suppressed in favor of safe status/upstream
status records. Fatal proxy configuration errors still go to stderr.
Application code must continue to use safe, fixed log messages and approved
metadata; the formatter is not a general-purpose sanitizer for arbitrary strings.

The default level is INFO. Supported values are DEBUG, INFO, WARNING, ERROR and
CRITICAL. For host execution, set `LOG_LEVEL` before starting the service. For
Docker, set it in root `.env`, regenerate `.env.docker`, and recreate containers:

```powershell
.\.venv\Scripts\python.exe infrastructure/docker/prepare_env.py
docker compose --env-file .env.docker -f compose.yaml -f compose.apps.yaml up -d --build --wait
```

The application containers use Docker's `local` log driver with a 10 MB rotation
size and three retained files per container. Older generated logs roll over;
database Activity Log records and application data are unaffected. No new Python
log files, database tables, or external logging services are created.

## Verify

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s forum_logging/tests -v
```

Service suites also cover real framework middleware installation, response
preservation, and request-ID headers. Shared tests cover privacy, error handling,
streaming, concurrent context isolation, WebSocket metadata and lifespan handling.

Logging verification passed 11 shared tests plus the full service suites:
136 Identity, 186 Discussion, 190 Notification & Realtime and 101 Search tests
(624 total, including the existing opt-in backend integration tests).
Live Docker checks verified matching gateway/backend request IDs, forwarded
Discussion-to-Identity IDs and WebSocket lifecycle logging. Credential and private
query/header/path canaries were absent from the inspected logs. Verification
sessions were logged out afterward.
