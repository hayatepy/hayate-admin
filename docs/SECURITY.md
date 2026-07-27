# Security and trust boundaries

`hayate-admin` is a privileged internal surface. Treat deploying it as granting
database-changing capabilities to an operations identity.

## Authentication and authorization

The package owns neither users nor sessions. `AdminSite` requires an async
authorizer and has no default. The application must authenticate with
hayate-auth, Cloudflare Access, OAuth, an API gateway, or another reviewed
identity system before returning an `Actor`.

The authorizer receives the exact action, resource, and optional object ID.
Resource-level permission is not object-level permission: object routes call
the policy again with the decoded ID. Hiding a link is never an authorization
decision.

Bulk POSTs require `resource:bulk`, the action's declared change/delete
permission at resource scope, and that permission again for every selected
object ID. Any denial stops the entire callback before storage runs.

CSV GETs require the separate `resource:export` action at resource scope and
again for every returned object ID. Grant export more narrowly than ordinary
viewing when records contain operationally sensitive fields. Cross-site Fetch
Metadata is rejected before the export callback runs.

Relationship choices require permission for the target resource and for each
returned target object. A submitted relationship ID is resolved again through
the application callback in the current request/tenant scope and authorized as
that exact target object. An ID accepted on another tenant, account, or request
must resolve to `None`; labels from rejected IDs are never rendered.

Inline routes authorize the exact parent, target resource, and child operation.
Update and delete IDs must occur in the reader's complete parent-scoped
snapshot before the mutator is called. This UI check is defense in depth: the
mutator must repeat tenant and parent membership checks in its storage
statement.

## Cross-site requests

Every POST requires an `Origin` exactly matching `allowed_origins`. Requests
whose `Sec-Fetch-Site` is cross-site are rejected before authorization or
storage. Session cookies must still be `Secure`, `HttpOnly`, and an appropriate
`SameSite` value. Origin checking does not replace authentication.

Only bounded `application/x-www-form-urlencoded` forms are accepted in the
initial release. File uploads, unexpected fields, and duplicate scalar fields
fail closed. Repeated `selected` values are accepted only by the bulk route.

## Output and browser policy

Record values, labels, translated validation messages, branding wordmarks,
actor display names, URLs, and attributes are HTML-escaped. The built-in
response policy is `no-store`, uses `frame-ancestors 'none'`, denies external
content by default, permits same-origin form actions and htmx connections, and
sets `nosniff`.

An optional htmx asset must be a same-origin absolute path with an SRI
sha256/384/512 value. The application owns serving and updating that asset.

`AdminMessages` is immutable and scoped to one site. Overrides may select only
known keys, must preserve simple named placeholders, and cannot use attribute
or item access, conversions, format specifications, or control characters.
Messages are still escaped at their final HTML context. Application validator
messages are treated as untrusted text too.

`AdminBranding` accepts only an escaped plain-text wordmark. `AdminTheme`
accepts six-digit hex color tokens and one of two fixed density values, then
enforces minimum contrast before rendering. The package never accepts raw
HTML, scripts, event handlers, arbitrary attributes, CSS declarations, or
remote stylesheet URLs. Its deterministic built-in stylesheet is allowed by
an exact SHA-256 `style-src` hash; the policy does not add `unsafe-inline`.

Applications needing arbitrary visual components should build a separate
purpose-specific Hayate view with its own security review instead of widening
the privileged admin renderer's extension boundary.

## Repository boundary

The repository receives typed field values and a `ListQuery`; it never receives
request query strings or HTML form objects. Implementations must map
`ListQuery.order_by` through their own static statement selection. Do not
interpolate it into SQL, even though the site already allowlists it.

Generated hayate-sql functions are the recommended boundary. Transactions,
optimistic concurrency, referential integrity, and row-level authorization
remain repository responsibilities.

Saved views contain only resource-validated search, choice filters, sort field,
and direction. They are not storage queries or authorization rules. A caller
may override a saved view only through the same ordinary allowlisted controls.

Cursor resources receive a repository continuation through `ListQuery.cursor`
and return another through `CursorPage`. The site envelopes that continuation
with the resource and a SHA-256 fingerprint of normalized query controls, then
rejects malformed, cross-resource, and cross-query reuse without duplicating
those values in the token. The envelope is deliberately not an authorization
credential: repositories must validate their own cursor version, shape, sort
mode, and keyset values, and every returned record is still authorized. Raise
`AdminCursorError` for an unsupported continuation so the site returns a
generic 400 without reflecting parser details. Never put SQL, secrets, tenant
identifiers, or unsigned permission claims in a cursor.

Relationship search and resolution callbacks must query only the current
tenant or account. Search returns a bounded `RelationshipPage`; resolution
returns one `RelationshipChoice` or `None`. List/detail repositories must
preload every relationship display field in their checked query. The admin
rejects a relationship ID without its declared display value, preventing
implicit per-row fetches and N+1 behavior.
Relationship create/update statements must repeat the target tenant/account
condition rather than relying only on the earlier resolver. A composite
tenant/parent foreign key is recommended where the database supports it.

An inline reader returns one complete `InlineCollection` of at most the
declared `max_items` children. One request carries exactly one
`InlineMutation`; there is no generic cascade or multi-row formset commit.
Create should use a checked `INSERT ... SELECT` or equivalent parent existence
condition. Update/delete should include tenant, parent ID, and child ID in the
same `WHERE` clause. The SQLite and D1 examples use those semantics, so a
concurrent move or cross-tenant ID substitution cannot widen the write.

Bulk callbacks receive only the request context, resolved repository, and a
deduplicated tuple of at most 100 already-authorized IDs. They must return a
`BulkActionResult` that partitions every ID into success or failure. The
repository owns all-or-nothing versus partial transaction semantics; failure
messages must not contain secrets or submitted record values.

CSV callbacks receive only the request context, resolved repository, and an
`ExportQuery` made from the same allowlisted controls. They must use a static
checked statement and obey the supplied limit. The site rejects a result above
`max_rows`, authorizes every record, serializes only configured fields,
neutralizes spreadsheet formula prefixes, and rejects output above
`max_bytes`. Exported values are intentionally sensitive application data even
though audit events remain value-free; protect downloaded files and review the
field allowlist independently from list display.

Cloudflare D1 and similar runtime bindings exist only on the request context.
Use an `AdminRepositoryFactory` to resolve the repository from that context;
never mutate a global repository to point at the current request. The factory
is synchronous and must return a complete repository before an operation runs.

## Audit boundary

`AuditEvent` intentionally contains no submitted values, record snapshots, SQL,
headers, cookies, or tokens. It records time, phase, action, optional registered
operation slug, resource, object ID, actor ID, and error type.

The injected sink should be durable. An attempt-event failure stops the
mutation. A success-event failure occurs after the repository returned and
cannot generically roll back across all databases; repositories that require
atomic data-and-audit commits should perform their own transactional audit and
use the site sink as an external security signal.

Use `audit_factory` when the durable sink depends on a request-local platform
binding. Exactly one static `audit` or request-scoped `audit_factory` is
required.

## Object history boundary

History is disabled unless an `AuditHistoryReader` or request-scoped factory is
configured. The route requires the separate `resource:history` permission for
the exact object ID. Reader results are capped at 50 per page and rejected if
any event names another resource or object.

The reader contract can return only `AuditEvent` metadata. Do not reconstruct
record snapshots or submitted form values for this UI. Actor IDs and error
types are still operationally sensitive, so grant history access more narrowly
than ordinary record viewing when appropriate.

## Denial-of-service controls

- form body: 64 KiB;
- individual field: at most 16 KiB and usually the lower field maximum;
- search: 200 characters;
- relationship search: 200 characters and at most 100 choices per page;
- filter choices: 100 per field;
- page size: 100 records;
- inline collection: complete and at most 100 records, with a configurable
  lower per-inline maximum;
- selected bulk IDs: 100, or the action's lower declared limit;
- repository cursor: 1,536 URL-safe characters inside a 4,096-character
  URL-safe, resource/query-bound envelope;
- CSV export: configured at 1–10,000 rows and 1 KiB–10 MiB, with the callback
  asked for one extra row to detect truncation;
- object history: 50 events per page;
- page number: 1–1,000,000;
- repository result: no more than the requested page.

Applications still need request timeouts, rate limits, database statement
timeouts, and operator-session expiration.
