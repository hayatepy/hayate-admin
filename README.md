# hayate-admin

> **Hayate ecosystem:** [Start here](https://github.com/hayatepy/.github/blob/main/docs/START.md)
> · [Hayate](https://github.com/hayatepy/hayate)
> · [Roadmap epic](https://github.com/hayatepy/roadmap/issues/12)

Secure operational administration for Hayate, using explicit resources and
checked SQL rather than ORM or database reflection.

> **Status: pre-release.** The typed CRUD and security core is implemented.
> The SQLite/generated-SQL and browser reference path is implemented. The
> package must not be described as Django admin parity until the Workers/D1
> evidence in
> [#3](https://github.com/hayatepy/hayate-admin/issues/3) is complete.

`hayate-admin` is an internal management tool for trusted operators. Public,
process-centric customer workflows should remain purpose-built application
views.

## Why it is explicit

Django can infer an administration interface from ORM model metadata. Hayate
does not have or want an ORM in its core. An `AdminResource` instead names
every exposed field and receives one repository object. The repository is
normally a thin adapter around generated
[hayate-sql](https://github.com/hayatepy/hayate-sql) functions.

The UI receives only a bounded `ListQuery`:

- search text, capped at 200 characters;
- choice filters declared by the resource;
- one declared sortable field and direction;
- offset and a page size capped at 100.

It never receives SQL text, column expressions, table names, or generic
database access.

## Minimal integration

```python
from hayate import Hayate
from hayate_admin import (
    Actor,
    AdminField,
    AdminResource,
    AdminSite,
    AuditEvent,
    ListQuery,
    Page,
)

app = Hayate()


class UserRepository:
    async def list(self, query: ListQuery) -> Page:
        # Call generated hayate-sql list/count functions here.
        ...

    async def get(self, object_id: str):
        ...

    async def create(self, values):
        ...

    async def update(self, object_id: str, values):
        ...

    async def delete(self, object_id: str) -> bool:
        ...


async def authorize(context, action, resource, object_id):
    # Resolve the application session/Access/OAuth principal and make the exact
    # site/resource/action/object decision. Returning None denies the request.
    user = context.get("user")
    if user is None or not user["is_operator"]:
        return None
    return Actor(id=user["id"], display=user["email"])


async def audit(event: AuditEvent) -> None:
    # Store or forward the redacted event. AuditEvent has no submitted-values
    # field by design.
    await security_events.write(event)


site = AdminSite(
    title="Operations",
    allowed_origins={"https://admin.example.com"},
    authorize=authorize,
    audit=audit,
)
site.add(
    AdminResource(
        slug="users",
        label="Users",
        singular_label="User",
        repository=UserRepository(),
        title_field="email",
        fields=(
            AdminField("id", "ID", required=False, read_only=True, sortable=True),
            AdminField("email", "Email", kind="email", searchable=True, sortable=True),
            AdminField(
                "status",
                "Status",
                kind="select",
                choices=(("active", "Active"), ("suspended", "Suspended")),
                filterable=True,
            ),
        ),
    )
)
site.register(app)
```

There is deliberately no default authorizer, no anonymous mode, and no
built-in superuser.

## Security contract

Every mutation follows this order:

1. reject cross-site Fetch Metadata and require an exact configured `Origin`;
2. authorize the exact action and optional object ID;
3. emit a redacted attempt event;
4. parse at most 64 KiB of URL-encoded fields and validate declared types;
5. call the injected repository;
6. emit success or a parameter-free failure event.

Full pages and htmx fragments use the same escaped renderer. Responses are
`no-store`, set a restrictive CSP, deny framing, and vary on all request
headers that select a page or fragment. Optional htmx JavaScript must be
self-hosted with a valid SRI hash:

```python
from hayate_admin import AdminAsset

AdminAsset(
    url="/assets/htmx-2.0.10.min.js",
    integrity="sha384-...",
)
```

Read [the threat model](docs/SECURITY.md) before deploying.

## Current surface

- resource index with per-resource authorization;
- paginated/searchable/filterable/sortable change list;
- record detail;
- add and edit forms with accessible inline errors;
- delete confirmation;
- full-page and htmx fragment representations;
- ordinary `303` post/redirect/get and htmx `HX-Redirect`;
- application-injected authorization and redacted audit events.

Bulk actions, relationships/autocomplete, saved filters, object history, and
internationalization remain tracked Phase 2 work. They are not implied by the
initial package.

## Executable SQLite reference

The [SQLite example](examples/sqlite/README.md) combines real hayate-auth
sessions, separately provisioned viewer/editor/operator roles, generated
hayate-sql list/count/get/create/update/delete functions, persistent redacted
audit rows, and a Chromium CRUD/search/filter/sort gate. It is the complete
minimal integration for the initial package contract.

## Development

Until `hayate-htmx` completes its first PyPI publication, `uv.lock` resolves
the reviewed 0.2.0 source commit. Published `hayate-admin` artifacts will
depend on the normal `hayate-htmx>=0.2,<1` package range.

```sh
uv sync --locked
uv run ruff check src examples tests typing_tests
uv run ruff format --check src examples tests typing_tests
uv run mypy src examples typing_tests
uv run pytest -q
uv build
uv run python scripts/check_dist.py
```

## License

MIT
