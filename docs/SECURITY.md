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

## Cross-site requests

Every POST requires an `Origin` exactly matching `allowed_origins`. Requests
whose `Sec-Fetch-Site` is cross-site are rejected before authorization or
storage. Session cookies must still be `Secure`, `HttpOnly`, and an appropriate
`SameSite` value. Origin checking does not replace authentication.

Only bounded `application/x-www-form-urlencoded` forms are accepted in the
initial release. File uploads, unexpected fields, and duplicate scalar fields
fail closed. Repeated `selected` values are accepted only by the bulk route.

## Output and browser policy

Record values, labels, validation messages, actor display names, URLs, and
attributes are HTML-escaped. The built-in response policy is `no-store`, uses
`frame-ancestors 'none'`, denies external content by default, permits
same-origin form actions and htmx connections, and sets `nosniff`.

An optional htmx asset must be a same-origin absolute path with an SRI
sha256/384/512 value. The application owns serving and updating that asset.

## Repository boundary

The repository receives typed field values and a `ListQuery`; it never receives
request query strings or HTML form objects. Implementations must map
`ListQuery.order_by` through their own static statement selection. Do not
interpolate it into SQL, even though the site already allowlists it.

Generated hayate-sql functions are the recommended boundary. Transactions,
optimistic concurrency, referential integrity, and row-level authorization
remain repository responsibilities.

Bulk callbacks receive only the request context, resolved repository, and a
deduplicated tuple of at most 100 already-authorized IDs. They must return a
`BulkActionResult` that partitions every ID into success or failure. The
repository owns all-or-nothing versus partial transaction semantics; failure
messages must not contain secrets or submitted record values.

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
- filter choices: 100 per field;
- page size: 100 records;
- selected bulk IDs: 100, or the action's lower declared limit;
- object history: 50 events per page;
- page number: 1–1,000,000;
- repository result: no more than the requested page.

Applications still need request timeouts, rate limits, database statement
timeouts, and operator-session expiration.
