# hayate-admin

> **Hayate ecosystem:** [Start here](https://github.com/hayatepy/.github/blob/main/docs/START.md)
> · [Hayate](https://github.com/hayatepy/hayate)
> · [Roadmap epic](https://github.com/hayatepy/roadmap/issues/12)

Secure operational administration for Hayate, using explicit resources and
checked SQL rather than ORM or database reflection.

> **Status: pre-release.** The typed CRUD and security core is implemented.
> The SQLite/generated-SQL, browser, and native Workers/D1 reference paths are
> implemented, including explicit searchable relationships and bounded inline
> editing, saved views, keyset cursors, policy-safe CSV export, application-scoped
> localization, bounded branding, and an automated WCAG A/AA audit. General
> Django admin parity is not claimed; Django's ORM-derived workflows and mature
> third-party extension ecosystem remain broader.

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
- either a bounded offset or an opaque, query-bound repository cursor;
- a page size capped at 100.

It never receives SQL text, column expressions, table names, or generic
database access.

Relationships are explicit too. An `AdminRelationship` names the source ID
field, target resource, preloaded display field, bounded search callback, and
single-ID resolver. An `AdminInline` names the reverse parent field, editable
fields, maximum child count, complete bounded reader, and one-record mutation
callback. Neither contract performs reflection or lazy loading.

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

## Saved views, cursor pagination, and CSV

Saved views are static metadata over the same declared search, filter, and sort
controls. They cannot store SQL, table names, arbitrary parameters, or a
permission decision:

```python
from hayate_admin import AdminCsvExport, AdminSavedView, CursorPage, ExportQuery


async def export_users(context, repository, query: ExportQuery):
    # Select one checked statement, bind query values, and obey query.limit.
    return await repository.export(query)


users = AdminResource(
    # ...explicit fields and repository...
    pagination="cursor",
    saved_views=(
        AdminSavedView(
            "suspended",
            "Suspended users",
            filters={"status": "suspended"},
            order_by="email",
        ),
    ),
    csv_export=AdminCsvExport(
        ("id", "email", "status"),
        export_users,
        filename="users.csv",
        max_rows=1_000,
        max_bytes=1_048_576,
    ),
)
```

A cursor-mode repository returns `CursorPage(items, next_cursor)`. The
continuation is repository-owned and must encode only a checked keyset, never
SQL. The site wraps it in an opaque envelope bound to the resource, saved view,
search, filters, and sort by a canonical SHA-256 fingerprint. Changing any of
those controls invalidates the cursor without duplicating their values inside
the token. A repository raises `AdminCursorError` for an unsupported
continuation, which becomes a generic `400` response without reflecting cursor
internals.

CSV is a separate `resource:export` capability. Its callback receives an
`ExportQuery` with a hard `max_rows + 1` limit so the site can reject
truncation instead of silently producing partial evidence. Every returned
record is authorized again at object scope. Only configured fields are
serialized; spreadsheet formula prefixes are neutralized; responses are
bounded by rows and UTF-8 bytes and are never rendered through htmx.

## Relationships and inlines

Declare the stored ID and preloaded display label as ordinary fields, then
attach explicit callbacks:

```python
from hayate_admin import AdminInline, AdminRelationship

tasks = AdminResource(
    slug="tasks",
    label="Tasks",
    singular_label="Task",
    repository=task_repository,
    fields=(
        AdminField("id", "ID", required=False, read_only=True),
        AdminField("name", "Name"),
        AdminField("parent_id", "Parent task", required=False, list_display=False),
        AdminField(
            "parent_name",
            "Parent name",
            required=False,
            read_only=True,
            list_display=False,
        ),
    ),
    relationships=(
        AdminRelationship(
            "parent_id",
            "tasks",
            "parent_name",
            search_parents,
            resolve_parent,
            max_choices=25,
        ),
    ),
    inlines=(
        AdminInline(
            "subtasks",
            "Subtasks",
            "tasks",
            "parent_id",
            ("name",),
            read_subtasks,
            mutate_subtask,
            max_items=10,
        ),
    ),
    title_field="name",
)
```

`search_parents` and `resolve_parent` must be tenant-scoped. List/get queries
must return `parent_name` whenever `parent_id` is non-null. `read_subtasks`
returns the complete bounded child set, and `mutate_subtask` owns one atomic
parent/tenant-checked write. See the shared
[SQLite/D1 task resource](examples/tasks.py) for complete typed callbacks and
checked SQL.

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

## Localization, branding, and accessibility

`AdminMessages` is immutable and belongs to one `AdminSite`. English is the
only bundled catalog; an application can provide a validated BCP 47-style
locale tag and override any stable catalog key. Missing overrides fall back to
English. There is no process-global active locale, import-time locale mutation,
implicit request-language negotiation, or dependency on ambient thread state.

```python
from hayate_admin import AdminBranding, AdminMessages, AdminSite, AdminTheme

messages = AdminMessages(
    locale="ja",
    overrides={
        "accessibility.skip_to_main": "本文へ移動",
        "list.search": "検索",
        "list.apply": "適用",
        "form.create_heading": "{item}を追加",
        "validation.required": "必須項目です。",
    },
)
branding = AdminBranding(
    wordmark="Hayate 運用",
    theme=AdminTheme(accent="#005EA8", density="compact"),
)

site = AdminSite(
    title="Operations",
    allowed_origins={"https://admin.example.com"},
    authorize=authorize,
    audit=audit,
    messages=messages,
    branding=branding,
)
```

Templates accept only the named placeholders declared by the English source
message. Resource labels, choice labels, application validator messages,
record values, and date/number formatting remain application-owned. Count
messages use explicit `.one` and `.other` keys rather than guessing a locale's
plural rules.

Branding is intentionally not a raw template hook. A wordmark is escaped plain
text. Themes accept only six-digit color tokens and a
`comfortable`/`compact` density; required text, link, muted text, and focus
contrast is checked when the site is constructed. Arbitrary HTML, attributes,
scripts, remote stylesheets, and custom CSS are not accepted. The deterministic
stylesheet is authorized by its exact SHA-256 CSP hash.

The Chromium gate runs pinned `axe-core` against the empty/list, create/edit,
detail, relationship, inline, bulk, saved-view, history, and delete states
using WCAG 2.0, 2.1, and 2.2 A/AA rule tags. The renderer also provides
landmarks, a skip link, visible keyboard focus, reduced-motion handling, table
headers/captions, explicit labels, and live status/error semantics. Automated
checks do not replace keyboard, screen-reader, zoom, or human usability review.

## Current surface

- resource index with per-resource authorization;
- paginated/searchable/filterable/sortable change list;
- record detail;
- add and edit forms with accessible inline errors;
- searchable, paginated to-one relationship choices with tenant-scoped
  resolution, per-target authorization, and preloaded display values;
- bounded reverse inline create/update/delete with one independently
  authorized and audited record mutation per request;
- delete confirmation;
- allowlisted bulk actions with bounded selection, per-object authorization,
  explicit partial results, and operation-tagged audit evidence;
- named saved views composed from allowlisted controls;
- opt-in forward keyset pagination with query-bound opaque cursor envelopes;
- separately authorized, field-allowlisted CSV with per-object checks,
  spreadsheet-cell protection, and hard row/byte limits;
- separately authorized, paginated per-object history backed only by redacted
  audit events;
- full-page and htmx fragment representations;
- ordinary `303` post/redirect/get and htmx `HX-Redirect`;
- application-injected authorization and redacted audit events.
- immutable per-site message catalogs with English defaults and safe custom
  locale overlays;
- plain-text branding and contrast-checked theme tokens under a hashed CSP;
- a pinned real-browser WCAG A/AA axe audit over every operational flow.

## Executable SQLite reference

The [SQLite example](examples/sqlite/README.md) combines real hayate-auth
sessions, separately provisioned viewer/editor/operator roles, generated
hayate-sql list/count/get/create/update/delete/bulk-close functions, persistent
redacted audit rows, explicit same-tenant task relationships, bounded subtasks,
saved views, keyset list queries, policy-safe CSV, and a Chromium
CRUD/search/filter/sort/bulk/relationship/inline/export gate. It is the complete
minimal integration for the current package contract.

The [Workers/D1 gate](examples/workers_d1/README.md) packages the exact same
resource and generated query facade into workerd. It exercises the full
authorization, mutation, CRUD, bulk, relationship, inline, object-history,
saved-view, cursor, CSV, escaping, audit, page, and fragment contract without
ASGI.

## Development

Until `hayate-htmx` completes its first PyPI publication, `uv.lock` resolves
the reviewed 0.2.0 source commit. Published `hayate-admin` artifacts will
depend on the normal `hayate-htmx>=0.2,<1` package range.

Release tags are immutable. The existing `v0.2.0` tag contains saved views,
keyset pagination, and bounded CSV export. After `hayate-htmx 0.2` is public,
publish that tag unchanged, then create `v0.3.0` from reviewed main for the
localization, branding, CSP, and accessibility additions. Never move or reuse
either tag.

```sh
uv sync --locked
uv run ruff check src examples tests typing_tests
uv run ruff format --check src examples tests typing_tests
uv run mypy src examples typing_tests
uv run pytest -q
npm ci --ignore-scripts
HAYATE_ADMIN_BROWSER_TESTS=1 uv run pytest tests/browser/test_sqlite_admin.py -q
uv build
uv run python scripts/check_dist.py
```

## License

MIT
