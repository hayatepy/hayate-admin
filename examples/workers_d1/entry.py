"""Native Cloudflare Python Workers + D1 hayate-admin probe."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hayate import Context, Hayate, Response
from hayate.adapters.workers import to_workers
from hayate_sql.adapters import D1Database

from hayate_admin import (
    Actor,
    AdminAction,
    AdminResource,
    AdminSite,
    AuditEvent,
    AuditHistoryReader,
    AuditSink,
)

if TYPE_CHECKING:
    from examples import tasks
    from examples.sqlite import generated_queries as task_queries
    from examples.sqlite.generated_queries import (
        create_admin_audit_event,
        list_admin_audit_events,
    )
else:
    import generated_queries as task_queries
    from generated_queries import create_admin_audit_event, list_admin_audit_events

    import tasks

TaskRepository = tasks.TaskRepository
task_resource = tasks.task_resource
audit_history_reader = tasks.audit_history_reader

_ORIGIN = "http://127.0.0.1:8796"
_TENANT_KEY = "hayate_admin_example_tenant"
_ROLE_ACTIONS: dict[str, frozenset[AdminAction]] = {
    "viewer": frozenset({"site:view", "resource:view"}),
    "operator": frozenset(
        {
            "site:view",
            "resource:view",
            "resource:add",
            "resource:change",
            "resource:delete",
            "resource:bulk",
            "resource:export",
            "resource:history",
        }
    ),
}


def _database(context: Context) -> D1Database:
    return D1Database(context.env.DB).with_session("first-primary")


def repository_factory(context: Context) -> TaskRepository:
    tenant_key = context.get(_TENANT_KEY)
    if not isinstance(tenant_key, str):
        raise RuntimeError("D1 repository resolved before tenant authorization")
    return TaskRepository(
        _database(context),
        task_queries,
        tenant_key=tenant_key,
    )


def audit_factory(context: Context) -> AuditSink:
    database = _database(context)

    async def audit(event: AuditEvent) -> None:
        await create_admin_audit_event(
            database,
            occurred_at=event.occurred_at.isoformat(),
            phase=event.phase,
            action=event.action,
            operation=event.operation or "",
            resource=event.resource or "site",
            object_id=event.object_id or "",
            actor_id=event.actor_id or "",
            error_type=event.error_type or "",
        )

    return audit


def history_factory(context: Context) -> AuditHistoryReader:
    return audit_history_reader(_database(context), task_queries)


async def authorize(
    context: Context,
    action: AdminAction,
    resource: AdminResource | None,
    object_id: str | None,
) -> Actor | None:
    del resource, object_id
    authorization = context.req.header("authorization") or ""
    scheme, separator, identity = authorization.partition(" ")
    role, tenant_separator, tenant_key = identity.partition(":")
    if not tenant_separator:
        tenant_key = "alpha"
    if (
        scheme != "Bearer"
        or separator != " "
        or action not in _ROLE_ACTIONS.get(role, ())
        or not tenant_key
        or len(tenant_key) > 120
        or any(ord(character) < 0x20 for character in tenant_key)
    ):
        return None
    context.set(_TENANT_KEY, tenant_key)
    return Actor(f"workerd-{role}-{tenant_key}", f"Workerd {role} ({tenant_key})")


app = Hayate()
admin = AdminSite(
    title="D1 Operations",
    allowed_origins={_ORIGIN},
    authorize=authorize,
    audit_factory=audit_factory,
    history_factory=history_factory,
)
admin.add(task_resource(repository_factory))
admin.register(app)


@app.get("/")
async def index(context: Context) -> Response:
    return context.json(
        {
            "runtime": "cloudflare-python-workers",
            "storage": "d1",
            "asgi": False,
        }
    )


@app.get("/probe/audit")
async def audit_probe(context: Context) -> Response:
    if await authorize(context, "site:view", None, None) is None:
        return context.json({"error": "forbidden"}, 403)
    return context.json(await list_admin_audit_events(_database(context)))


Default = to_workers(app)
