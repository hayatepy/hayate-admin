"""Executable SQLite admin backed only by generated hayate-sql functions."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from hayate import Context, Hayate, Request, Response
from hayate_auth import Auth
from hayate_auth.adapters.sqlite import SQLiteAdapter
from hayate_sql.adapters import SQLiteDatabase

from hayate_admin import (
    Actor,
    AdminAction,
    AdminResource,
    AdminSite,
    AuditEvent,
)

from ..tasks import TaskRepository, task_resource
from . import generated_queries as task_queries
from .generated_queries import (
    create_admin_audit_event,
    get_admin_role,
    upsert_admin_role,
)

type AdminRole = Literal["viewer", "editor", "operator"]

_ROOT = Path(__file__).parent
_IDENTITY_KEY = "hayate_admin_example_identity"
_ACTIONS: Mapping[AdminRole, frozenset[AdminAction]] = {
    "viewer": frozenset({"site:view", "resource:view"}),
    "editor": frozenset(
        {
            "site:view",
            "resource:view",
            "resource:add",
            "resource:change",
            "resource:bulk",
        }
    ),
    "operator": frozenset(
        {
            "site:view",
            "resource:view",
            "resource:add",
            "resource:change",
            "resource:delete",
            "resource:bulk",
        }
    ),
}


def initialize_database(path: str | Path) -> None:
    """Apply the example's forward migration to a new SQLite database."""
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"refusing to initialize existing database: {target}")
    migration = (_ROOT / "migrations/0001_create_tasks.sql").read_text()
    connection = sqlite3.connect(str(target))
    try:
        connection.executescript(migration)
    finally:
        connection.close()


@dataclass(frozen=True, slots=True)
class _Identity:
    actor: Actor
    role: AdminRole


@dataclass(slots=True)
class ExampleApplication:
    app: Hayate
    database: SQLiteDatabase
    auth_adapter: SQLiteAdapter
    auth: Auth
    closed: bool = False

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self.database.close()
        self.auth_adapter.close()


def create_example(
    *,
    database_path: str | Path,
    origin: str,
    auth_secret: str,
) -> ExampleApplication:
    """Build the example after its migration has been applied."""
    database = SQLiteDatabase(database_path)
    auth_adapter = SQLiteAdapter(str(database_path))
    auth_adapter.create_tables()
    auth = Auth(
        secret=auth_secret,
        adapter=auth_adapter,
        trusted_origins=(origin,),
    )
    app = Hayate()
    auth.register(app)

    async def identity(context: Context) -> _Identity | None:
        cached = context.get(_IDENTITY_KEY)
        if isinstance(cached, _Identity):
            return cached
        resolved = await auth.get_session(context.req.raw)
        if resolved is None:
            return None
        user, _ = resolved
        user_id = user.get("id")
        email = user.get("email")
        if not isinstance(user_id, str) or not isinstance(email, str):
            return None
        role_row = await get_admin_role(database, user_id=user_id)
        if role_row is None or role_row["role"] not in _ACTIONS:
            return None
        role = cast(AdminRole, role_row["role"])
        resolved_identity = _Identity(Actor(user_id, email), role)
        context.set(_IDENTITY_KEY, resolved_identity)
        return resolved_identity

    async def authorize(
        context: Context,
        action: AdminAction,
        resource: AdminResource | None,
        object_id: str | None,
    ) -> Actor | None:
        del resource, object_id
        resolved_identity = await identity(context)
        if resolved_identity is None or action not in _ACTIONS[resolved_identity.role]:
            return None
        return resolved_identity.actor

    async def audit(event: AuditEvent) -> None:
        await create_admin_audit_event(
            database,
            occurred_at=event.occurred_at.isoformat(),
            phase=event.phase,
            action=event.action,
            operation=event.operation,
            resource=event.resource or "site",
            object_id=event.object_id,
            actor_id=event.actor_id,
            error_type=event.error_type,
        )

    admin = AdminSite(
        title="SQLite Operations",
        allowed_origins={origin},
        authorize=authorize,
        audit=audit,
    )
    admin.add(
        task_resource(
            TaskRepository(
                database,
                task_queries,
                list_scope=database.transaction,
                mutation_scope=database.transaction,
            )
        )
    )
    admin.register(app)

    @app.get("/")
    async def index(context: Context) -> Response:
        return context.redirect("/admin")

    example = ExampleApplication(app, database, auth_adapter, auth)

    @app.on_stop
    async def close() -> None:
        await example.close()

    return example


async def seed_user(
    *,
    database_path: str | Path,
    origin: str,
    auth_secret: str,
    email: str,
    password: str,
    role: AdminRole,
) -> str:
    """Create a demo identity, then grant its role outside the public auth API."""
    auth_adapter = SQLiteAdapter(str(database_path))
    auth_adapter.create_tables()
    auth = Auth(
        secret=auth_secret,
        adapter=auth_adapter,
        trusted_origins=(origin,),
    )
    try:
        response = await auth.fetch(
            Request(
                f"{origin}/api/auth/sign-up/email",
                method="POST",
                headers={"content-type": "application/json", "origin": origin},
                body=json.dumps({"email": email, "password": password}),
            )
        )
        payload = await response.json()
        if not response.ok or not isinstance(payload, dict):
            raise RuntimeError(f"could not create example user: HTTP {response.status}")
        user = payload.get("user")
        if not isinstance(user, dict):
            raise RuntimeError("auth response did not contain a user ID")
        user_id = user.get("id")
        if not isinstance(user_id, str):
            raise RuntimeError("auth response did not contain a user ID")
    finally:
        auth_adapter.close()

    database = SQLiteDatabase(database_path)
    try:
        await upsert_admin_role(database, user_id=user_id, role=role)
    finally:
        await database.close()
    return user_id


def create_server_app() -> Hayate:
    """Uvicorn factory configured exclusively through explicit environment."""
    path = os.environ.get("HAYATE_ADMIN_SQLITE_DB")
    origin = os.environ.get("HAYATE_ADMIN_ORIGIN", "http://127.0.0.1:8000")
    secret = os.environ.get("AUTH_SECRET")
    if path is None or secret is None:
        raise RuntimeError("HAYATE_ADMIN_SQLITE_DB and AUTH_SECRET are required")
    return create_example(database_path=path, origin=origin, auth_secret=secret).app
