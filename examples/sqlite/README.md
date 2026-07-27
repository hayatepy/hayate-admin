# SQLite + generated hayate-sql admin

This executable example combines four independently maintained Hayate
packages:

- `hayate-auth` owns password verification and revocable sessions;
- `hayate-sql` compiles native SQLite contracts and generates typed functions;
- `hayate-admin` owns fail-closed authorization and the operational UI;
- `hayate-htmx` selects full-page or progressive fragment representations.

There is no ORM, schema reflection, generic SQL builder, or database call in
`TaskRepository`. Search, filter, and sort choices select checked-in generated
functions; request values are only bound parameters.

## Compile the contracts

From the repository root:

```sh
uv sync --locked
uv run hayate-sql check examples/sqlite/queries \
  --dialect sqlite \
  --migrations examples/sqlite/migrations
uv run hayate-sql generate examples/sqlite/queries \
  -o /tmp/generated_queries.py
uv run ruff format /tmp/generated_queries.py
diff -u examples/sqlite/generated_queries.py /tmp/generated_queries.py
```

The migration, SQL contracts, and generated facade must agree before CI can
pass.

## Run locally

Initialize a new database, create an identity through hayate-auth, and grant
its role through the separate administration table:

```sh
export AUTH_SECRET="replace-with-a-random-production-secret"
export EXAMPLE_PASSWORD="replace-with-a-long-demo-password"
export HAYATE_ADMIN_ORIGIN="http://127.0.0.1:8000"
export HAYATE_ADMIN_SQLITE_DB="$PWD/admin-example.db"

uv run python -m examples.sqlite.manage init \
  --database "$HAYATE_ADMIN_SQLITE_DB"
uv run python -m examples.sqlite.manage seed \
  --database "$HAYATE_ADMIN_SQLITE_DB" \
  --origin "$HAYATE_ADMIN_ORIGIN" \
  --email operator@example.test \
  --role operator
uv run uvicorn examples.sqlite.app:create_server_app --factory
```

Sign in with `POST /api/auth/sign-in/email`, then open
`http://127.0.0.1:8000/admin`. A product would normally provide its own login
view or place the app behind an identity-aware proxy.

Roles are deliberately not self-asserted:

- `viewer` can view the site and resources;
- `editor` can also add and change records;
- `operator` can also delete records.

The public auth API cannot write `admin_role`. Provision roles through a
reviewed back-office or deployment process in a real application. Do not
expose the example seeding command to application users.

## Audit boundary

Every mutation writes an `admin_audit_event` using another generated query.
Rows contain time, phase, action, resource, object ID, actor ID, and error type.
They have no form-value, record-snapshot, SQL, cookie, or token column.

The real-browser gate signs in through hayate-auth, creates two records,
searches, filters, sorts, edits, deletes, checks browser errors, and verifies
the audit rows:

```sh
uv run playwright install chromium
HAYATE_ADMIN_BROWSER_TESTS=1 \
  uv run pytest tests/browser/test_sqlite_admin.py -q
```
