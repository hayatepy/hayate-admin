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

_ORIGIN = "http://127.0.0.1:8796"
_ROLE_ACTIONS: dict[str, frozenset[AdminAction]] = {
    "viewer": frozenset({"site:view", "resource:view"}),
    "operator": frozenset(
        {
            "site:view",
            "resource:view",
            "resource:add",
            "resource:change",
            "resource:delete",
        }
    ),
}


def _database(context: Context) -> D1Database:
    return D1Database(context.env.DB).with_session("first-primary")


def repository_factory(context: Context) -> TaskRepository:
    return TaskRepository(_database(context), task_queries)


def audit_factory(context: Context) -> AuditSink:
    database = _database(context)

    async def audit(event: AuditEvent) -> None:
        await create_admin_audit_event(
            database,
            occurred_at=event.occurred_at.isoformat(),
            phase=event.phase,
            action=event.action,
            resource=event.resource or "site",
            object_id=event.object_id,
            actor_id=event.actor_id,
            error_type=event.error_type,
        )

    return audit


async def authorize(
    context: Context,
    action: AdminAction,
    resource: AdminResource | None,
    object_id: str | None,
) -> Actor | None:
    del resource, object_id
    authorization = context.req.header("authorization") or ""
    scheme, separator, role = authorization.partition(" ")
    if scheme != "Bearer" or separator != " " or action not in _ROLE_ACTIONS.get(role, ()):
        return None
    return Actor(f"workerd-{role}", f"Workerd {role}")


app = Hayate()
admin = AdminSite(
    title="D1 Operations",
    allowed_origins={_ORIGIN},
    authorize=authorize,
    audit_factory=audit_factory,
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
