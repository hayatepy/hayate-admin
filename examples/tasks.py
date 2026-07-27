"""Shared checked-SQL repository and resource for SQLite and Workers/D1."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from typing import Protocol, cast

from hayate import Context
from hayate_sql import Database

from hayate_admin import (
    AdminAction,
    AdminBulkAction,
    AdminField,
    AdminInline,
    AdminRelationship,
    AdminRepository,
    AdminRepositoryFactory,
    AdminResource,
    AdminValidationError,
    AuditEvent,
    AuditHistoryPage,
    AuditHistoryReader,
    AuditPhase,
    BulkActionResult,
    InlineCollection,
    InlineMutation,
    InlineMutationResult,
    ListQuery,
    Page,
    Record,
    RelationshipChoice,
    RelationshipPage,
    RelationshipQuery,
)


class TaskQueryFacade(Protocol):
    """Generated functions consumed by the shared repository."""

    async def count_tasks(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        search: str,
        status: str,
    ) -> Mapping[str, object]: ...

    async def list_tasks_default(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        search: str,
        status: str,
        limit: int,
        offset: int,
    ) -> Sequence[Mapping[str, object]]: ...

    async def list_tasks_name_asc(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        search: str,
        status: str,
        limit: int,
        offset: int,
    ) -> Sequence[Mapping[str, object]]: ...

    async def list_tasks_name_desc(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        search: str,
        status: str,
        limit: int,
        offset: int,
    ) -> Sequence[Mapping[str, object]]: ...

    async def get_task(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        id: int,
    ) -> Mapping[str, object] | None: ...

    async def create_task(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        name: str,
        status: str,
        active: bool,
        notes: str,
        parent_id: int | None,
    ) -> Mapping[str, object] | None: ...

    async def update_task(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        id: int,
        name: str,
        status: str,
        active: bool,
        notes: str,
        parent_id: int | None,
    ) -> Mapping[str, object] | None: ...

    async def delete_task(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        id: int,
    ) -> Mapping[str, object] | None: ...

    async def close_task(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        id: int,
    ) -> Mapping[str, object] | None: ...

    async def count_task_relationship_choices(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        search: str,
        exclude_id: int | None,
    ) -> Mapping[str, object]: ...

    async def list_task_relationship_choices(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        search: str,
        exclude_id: int | None,
        limit: int,
        offset: int,
    ) -> Sequence[Mapping[str, object]]: ...

    async def get_task_relationship_choice(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        id: int,
        exclude_id: int | None,
    ) -> Mapping[str, object] | None: ...

    async def list_subtasks(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        parent_id: int,
        limit: int,
    ) -> Sequence[Mapping[str, object]]: ...

    async def create_subtask(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        parent_id: int,
        name: str,
        status: str,
        active: bool,
        notes: str,
    ) -> Mapping[str, object] | None: ...

    async def update_subtask(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        parent_id: int,
        id: int,
        name: str,
        status: str,
        active: bool,
        notes: str,
    ) -> Mapping[str, object] | None: ...

    async def delete_subtask(
        self,
        db: Database,
        /,
        *,
        tenant_key: str,
        parent_id: int,
        id: int,
    ) -> Mapping[str, object] | None: ...


class AuditQueryFacade(Protocol):
    """Generated audit functions consumed by both SQLite and D1 history."""

    async def count_admin_audit_events_for_object(
        self,
        db: Database,
        /,
        *,
        resource: str,
        object_id: str,
    ) -> Mapping[str, object]: ...

    async def list_admin_audit_events_for_object(
        self,
        db: Database,
        /,
        *,
        resource: str,
        object_id: str,
        limit: int,
        offset: int,
    ) -> Sequence[Mapping[str, object]]: ...


type ListScopeFactory = Callable[[], AbstractAsyncContextManager[object]]


@asynccontextmanager
async def _unscoped_list() -> AsyncIterator[None]:
    yield


def _integer_id(object_id: str) -> int | None:
    try:
        value = int(object_id)
    except ValueError:
        return None
    return value if value > 0 else None


def _task_record(row: Mapping[str, object]) -> Record:
    return {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "active": bool(row["active"]),
        "notes": row["notes"],
        "parent_id": row.get("parent_id"),
        "parent_name": row.get("parent_name"),
    }


def _string(values: Mapping[str, object], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str):
        raise AdminValidationError({name: "A string value is required."})
    return value


def _boolean(values: Mapping[str, object], name: str) -> bool:
    value = values.get(name)
    if not isinstance(value, bool):
        raise AdminValidationError({name: "A boolean value is required."})
    return value


def _optional_parent_id(values: Mapping[str, object]) -> int | None:
    value = values.get("parent_id")
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdminValidationError({"parent_id": "A related task ID is required."})
    parent_id = _integer_id(value)
    if parent_id is None:
        raise AdminValidationError({"parent_id": "Select a valid related task."})
    return parent_id


def _row_id(row: Mapping[str, object]) -> int:
    value = row.get("id")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("task query returned an invalid ID")
    return value


def _row_name(row: Mapping[str, object]) -> str:
    value = row.get("name")
    if not isinstance(value, str) or not value:
        raise ValueError("task query returned an invalid name")
    return value


def _required_string(row: Mapping[str, object], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str):
        raise ValueError(f"audit history returned an invalid {name}")
    return value


def _optional_string(row: Mapping[str, object], name: str) -> str | None:
    value = row.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"audit history returned an invalid {name}")
    return value


class TaskRepository:
    """Tenant-scoped static query selection with preloaded relationship labels."""

    def __init__(
        self,
        database: Database,
        queries: TaskQueryFacade,
        *,
        tenant_key: str,
        list_scope: ListScopeFactory | None = None,
        mutation_scope: ListScopeFactory | None = None,
    ) -> None:
        if (
            not isinstance(tenant_key, str)
            or not tenant_key
            or len(tenant_key) > 120
            or any(ord(character) < 0x20 for character in tenant_key)
        ):
            raise ValueError("task repository tenant_key must be bounded and printable")
        self._database = database
        self._queries = queries
        self._tenant_key = tenant_key
        self._list_scope = list_scope or _unscoped_list
        self._mutation_scope = mutation_scope or _unscoped_list

    async def list(self, query: ListQuery) -> Page:
        search = query.search or ""
        status = query.filters.get("status", "")
        async with self._list_scope():
            total = await self._queries.count_tasks(
                self._database,
                tenant_key=self._tenant_key,
                search=search,
                status=status,
            )
            if query.order_by is None:
                rows = await self._queries.list_tasks_default(
                    self._database,
                    tenant_key=self._tenant_key,
                    search=search,
                    status=status,
                    limit=query.limit,
                    offset=query.offset,
                )
            elif query.order_by == "name" and query.descending:
                rows = await self._queries.list_tasks_name_desc(
                    self._database,
                    tenant_key=self._tenant_key,
                    search=search,
                    status=status,
                    limit=query.limit,
                    offset=query.offset,
                )
            elif query.order_by == "name":
                rows = await self._queries.list_tasks_name_asc(
                    self._database,
                    tenant_key=self._tenant_key,
                    search=search,
                    status=status,
                    limit=query.limit,
                    offset=query.offset,
                )
            else:
                raise ValueError(f"unsupported task order: {query.order_by!r}")
        total_value = total.get("total")
        if not isinstance(total_value, int):
            raise ValueError("count_tasks returned an invalid total")
        return Page(tuple(_task_record(row) for row in rows), total_value)

    async def get(self, object_id: str) -> Record | None:
        task_id = _integer_id(object_id)
        if task_id is None:
            return None
        row = await self._queries.get_task(
            self._database,
            tenant_key=self._tenant_key,
            id=task_id,
        )
        return None if row is None else _task_record(row)

    async def create(self, values: Mapping[str, object]) -> Record:
        parent_id = _optional_parent_id(values)
        async with self._mutation_scope():
            created = await self._queries.create_task(
                self._database,
                tenant_key=self._tenant_key,
                name=_string(values, "name"),
                status=_string(values, "status"),
                active=_boolean(values, "active"),
                notes=_string(values, "notes"),
                parent_id=parent_id,
            )
            if created is None:
                raise AdminValidationError({"parent_id": "Select an authorized related record."})
            record = await self.get(str(_row_id(created)))
        if record is None:
            raise RuntimeError("created task was not visible in its tenant")
        return record

    async def update(
        self,
        object_id: str,
        values: Mapping[str, object],
    ) -> Record | None:
        task_id = _integer_id(object_id)
        if task_id is None:
            return None
        parent_id = _optional_parent_id(values)
        async with self._mutation_scope():
            updated = await self._queries.update_task(
                self._database,
                tenant_key=self._tenant_key,
                id=task_id,
                name=_string(values, "name"),
                status=_string(values, "status"),
                active=_boolean(values, "active"),
                notes=_string(values, "notes"),
                parent_id=parent_id,
            )
            if updated is None:
                if parent_id is not None:
                    raise AdminValidationError(
                        {"parent_id": "Select an authorized related record."}
                    )
                return None
            record = await self.get(str(task_id))
        if record is None:
            raise RuntimeError("updated task was not visible in its tenant")
        return record

    async def delete(self, object_id: str) -> bool:
        task_id = _integer_id(object_id)
        return (
            task_id is not None
            and await self._queries.delete_task(
                self._database,
                tenant_key=self._tenant_key,
                id=task_id,
            )
            is not None
        )

    async def close(self, object_ids: tuple[str, ...]) -> BulkActionResult:
        succeeded = []
        failed = {}
        async with self._mutation_scope():
            for object_id in object_ids:
                task_id = _integer_id(object_id)
                if task_id is None:
                    failed[object_id] = "Invalid task ID."
                    continue
                row = await self._queries.close_task(
                    self._database,
                    tenant_key=self._tenant_key,
                    id=task_id,
                )
                if row is None:
                    failed[object_id] = "Task no longer exists."
                else:
                    succeeded.append(object_id)
        return BulkActionResult(succeeded, failed)

    async def search_relationship(
        self,
        query: RelationshipQuery,
        source_object_id: str | None,
    ) -> RelationshipPage:
        exclude_id = None if source_object_id is None else _integer_id(source_object_id)
        if source_object_id is not None and exclude_id is None:
            return RelationshipPage((), 0)
        search = query.search or ""
        total_row = await self._queries.count_task_relationship_choices(
            self._database,
            tenant_key=self._tenant_key,
            search=search,
            exclude_id=exclude_id,
        )
        rows = await self._queries.list_task_relationship_choices(
            self._database,
            tenant_key=self._tenant_key,
            search=search,
            exclude_id=exclude_id,
            limit=query.limit,
            offset=query.offset,
        )
        total = total_row.get("total")
        if not isinstance(total, int) or isinstance(total, bool):
            raise ValueError("task relationship count returned an invalid total")
        return RelationshipPage(
            tuple(RelationshipChoice(str(_row_id(row)), _row_name(row)) for row in rows),
            total,
        )

    async def resolve_relationship(
        self,
        related_object_id: str,
        source_object_id: str | None,
    ) -> RelationshipChoice | None:
        related_id = _integer_id(related_object_id)
        exclude_id = None if source_object_id is None else _integer_id(source_object_id)
        if related_id is None or (source_object_id is not None and exclude_id is None):
            return None
        row = await self._queries.get_task_relationship_choice(
            self._database,
            tenant_key=self._tenant_key,
            id=related_id,
            exclude_id=exclude_id,
        )
        return None if row is None else RelationshipChoice(str(_row_id(row)), _row_name(row))

    async def read_subtasks(
        self,
        parent_object_id: str,
        limit: int,
    ) -> InlineCollection:
        parent_id = _integer_id(parent_object_id)
        if parent_id is None:
            return InlineCollection((), 0)
        rows = await self._queries.list_subtasks(
            self._database,
            tenant_key=self._tenant_key,
            parent_id=parent_id,
            limit=limit + 1,
        )
        if len(rows) > limit:
            raise ValueError("stored subtasks exceed the declared inline maximum")
        records = tuple(_task_record(row) for row in rows)
        return InlineCollection(records, len(records))

    async def mutate_subtask(
        self,
        parent_object_id: str,
        mutation: InlineMutation,
    ) -> InlineMutationResult:
        parent_id = _integer_id(parent_object_id)
        if parent_id is None:
            raise AdminValidationError({"__all__": "Parent task no longer exists."})
        child_id: int
        async with self._mutation_scope():
            if mutation.operation == "create":
                created = await self._queries.create_subtask(
                    self._database,
                    tenant_key=self._tenant_key,
                    parent_id=parent_id,
                    name=_string(mutation.values, "name"),
                    status=_string(mutation.values, "status"),
                    active=_boolean(mutation.values, "active"),
                    notes=_string(mutation.values, "notes"),
                )
                if created is None:
                    raise AdminValidationError({"__all__": "Parent task no longer exists."})
                child_id = _row_id(created)
            else:
                parsed_child_id = (
                    None if mutation.object_id is None else _integer_id(mutation.object_id)
                )
                if parsed_child_id is None:
                    raise AdminValidationError(
                        {"__all__": "Inline task no longer belongs to this parent."}
                    )
                child_id = parsed_child_id
                if mutation.operation == "delete":
                    deleted = await self._queries.delete_subtask(
                        self._database,
                        tenant_key=self._tenant_key,
                        parent_id=parent_id,
                        id=child_id,
                    )
                    if deleted is None:
                        raise AdminValidationError(
                            {"__all__": ("Inline task no longer belongs to this parent.")}
                        )
                    return InlineMutationResult(deleted=True)
                updated = await self._queries.update_subtask(
                    self._database,
                    tenant_key=self._tenant_key,
                    parent_id=parent_id,
                    id=child_id,
                    name=_string(mutation.values, "name"),
                    status=_string(mutation.values, "status"),
                    active=_boolean(mutation.values, "active"),
                    notes=_string(mutation.values, "notes"),
                )
                if updated is None:
                    raise AdminValidationError(
                        {"__all__": ("Inline task no longer belongs to this parent.")}
                    )
            record = await self.get(str(child_id))
        if record is None:
            raise RuntimeError("inline task was not visible after mutation")
        return InlineMutationResult(record)


async def _close_selected(
    context: Context,
    repository: AdminRepository,
    object_ids: tuple[str, ...],
) -> BulkActionResult:
    del context
    if not isinstance(repository, TaskRepository):
        raise TypeError("close action requires the task repository")
    return await repository.close(object_ids)


def _task_repository(context: Context, resource: AdminResource) -> TaskRepository:
    repository = resource.repository_for(context)
    if not isinstance(repository, TaskRepository):
        raise TypeError("task relations require the task repository")
    return repository


async def _search_task_relationship(
    context: Context,
    source_resource: AdminResource,
    target_resource: AdminResource,
    relationship: AdminRelationship,
    source_object_id: str | None,
    query: RelationshipQuery,
) -> RelationshipPage:
    del target_resource, relationship
    return await _task_repository(context, source_resource).search_relationship(
        query,
        source_object_id,
    )


async def _resolve_task_relationship(
    context: Context,
    source_resource: AdminResource,
    target_resource: AdminResource,
    relationship: AdminRelationship,
    source_object_id: str | None,
    related_object_id: str,
) -> RelationshipChoice | None:
    del target_resource, relationship
    return await _task_repository(context, source_resource).resolve_relationship(
        related_object_id,
        source_object_id,
    )


async def _read_subtasks(
    context: Context,
    parent_resource: AdminResource,
    target_resource: AdminResource,
    inline: AdminInline,
    parent_object_id: str,
    limit: int,
) -> InlineCollection:
    del target_resource, inline
    return await _task_repository(context, parent_resource).read_subtasks(
        parent_object_id,
        limit,
    )


async def _mutate_subtask(
    context: Context,
    parent_resource: AdminResource,
    target_resource: AdminResource,
    inline: AdminInline,
    parent_object_id: str,
    mutation: InlineMutation,
) -> InlineMutationResult:
    del target_resource, inline
    return await _task_repository(context, parent_resource).mutate_subtask(
        parent_object_id,
        mutation,
    )


def audit_history_reader(
    database: Database,
    queries: AuditQueryFacade,
) -> AuditHistoryReader:
    """Build the same checked, redacted history reader for SQLite and D1."""

    async def read_history(
        context: Context,
        resource: AdminResource,
        object_id: str,
        offset: int,
        limit: int,
    ) -> AuditHistoryPage:
        del context
        total_row = await queries.count_admin_audit_events_for_object(
            database,
            resource=resource.slug,
            object_id=object_id,
        )
        rows = await queries.list_admin_audit_events_for_object(
            database,
            resource=resource.slug,
            object_id=object_id,
            limit=limit,
            offset=offset,
        )
        total = total_row.get("total")
        if not isinstance(total, int):
            raise ValueError("audit history returned an invalid total")
        events = []
        for row in rows:
            phase = _required_string(row, "phase")
            action = _required_string(row, "action")
            if phase not in ("attempt", "success", "failure"):
                raise ValueError("audit history returned an invalid phase")
            if action not in (
                "site:view",
                "resource:view",
                "resource:add",
                "resource:change",
                "resource:delete",
                "resource:bulk",
                "resource:history",
            ):
                raise ValueError("audit history returned an invalid action")
            occurred_at = datetime.fromisoformat(_required_string(row, "occurred_at"))
            if occurred_at.tzinfo is None:
                raise ValueError("audit history timestamps must include a timezone")
            events.append(
                AuditEvent(
                    occurred_at=occurred_at,
                    phase=cast(AuditPhase, phase),
                    action=cast(AdminAction, action),
                    resource=_required_string(row, "resource"),
                    object_id=_optional_string(row, "object_id"),
                    actor_id=_optional_string(row, "actor_id"),
                    error_type=_optional_string(row, "error_type"),
                    operation=_optional_string(row, "operation"),
                )
            )
        return AuditHistoryPage(events, total)

    return read_history


def task_resource(
    repository: AdminRepository | AdminRepositoryFactory,
) -> AdminResource:
    """One exact resource definition reused by SQLite and Workers/D1."""
    return AdminResource(
        slug="tasks",
        label="Tasks",
        singular_label="Task",
        repository=repository,
        title_field="name",
        fields=(
            AdminField("id", "ID", required=False, read_only=True),
            AdminField("name", "Name", searchable=True, sortable=True, max_length=120),
            AdminField(
                "status",
                "Status",
                kind="select",
                choices=(("open", "Open"), ("closed", "Closed")),
                filterable=True,
            ),
            AdminField("active", "Active", kind="checkbox", required=False),
            AdminField(
                "notes",
                "Notes",
                kind="textarea",
                required=False,
                list_display=False,
                max_length=2000,
            ),
            AdminField(
                "parent_id",
                "Parent task",
                required=False,
                list_display=False,
            ),
            AdminField(
                "parent_name",
                "Parent task",
                required=False,
                read_only=True,
            ),
        ),
        bulk_actions=(
            AdminBulkAction(
                "close",
                "Close selected",
                "resource:change",
                _close_selected,
            ),
        ),
        relationships=(
            AdminRelationship(
                "parent_id",
                "tasks",
                "parent_name",
                _search_task_relationship,
                _resolve_task_relationship,
                max_choices=20,
            ),
        ),
        inlines=(
            AdminInline(
                "subtasks",
                "Subtasks",
                "tasks",
                "parent_id",
                ("name", "status", "active", "notes"),
                _read_subtasks,
                _mutate_subtask,
                max_items=10,
            ),
        ),
        page_size=10,
    )
