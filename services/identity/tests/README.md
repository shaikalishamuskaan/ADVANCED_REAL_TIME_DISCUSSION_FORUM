# Identity tests

Tests are grouped by the application they exercise:

- `accounts/`: profiles, usernames, passwords, and internal service APIs.
- `auth_flow/`: registration, login, refresh/logout, and rate limits.
- `admin_console/`: user management, roles, account status, recovery, and activity.
- `audit/`: event consumption, outbox publication, cleanup, and health checks.

Run from `services/identity` using Identity's virtual environment:

```powershell
.\.venv\Scripts\python.exe manage.py test --keepdb --noinput
```

Use Django's test runner for this service. Running `pytest -q` from the root
virtual environment fails because that environment does not contain Django or
Django REST Framework. Changing directories does not change the active virtual
environment; both environments can display the same `(.venv)` prompt. The
explicit Python path above selects Identity's environment without activation.

The pytest-asyncio warning belongs to the root environment's pytest plugins.
Identity's Django test command does not load those plugins. No dependency
installation or asyncio configuration change is needed for this command.

Run one group or module with its new package path:

```powershell
.\.venv\Scripts\python.exe manage.py test tests.admin_console --keepdb --noinput
.\.venv\Scripts\python.exe manage.py test tests.audit.test_consumer_redis --keepdb --noinput
```

The old application-level labels such as `audit.test_consumer_redis` have moved
under `tests`. Tests continue to import application code from its original
packages, such as `accounts.models` and `auth_flow.services`.
