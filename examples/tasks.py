"""Shared checked-SQL repository and resource for SQLite and Workers/D1."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from hayate_sql import Database

from hayate_admin import (
    AdminField,
    AdminRepository,
    AdminRepositoryFactory,
    AdminResource,
    AdminValidationError,
    ListQuery,
    Page,
    Record,
)


class TaskQueryFacade(Protocol):
    """Generated functions consumed by the shared repository."""

    async def count_tasks(
        self,
        db: Database,
        /,
        *,
        search: str,
        status: str,
    ) -> Mapping[str, object]: ...

    async def list_tasks_default(
        self,
        db: Database,
        /,
        *,
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
        id: int,
    ) -> Mapping[str, object] | None: ...

    async def create_task(
        self,
        db: Database,
        /,
        *,
        name: str,
        status: str,
        active: bool,
        notes: str,
    ) -> Mapping[str, object]: ...

    async def update_task(
        self,
        db: Database,
        /,
        *,
        id: int,
        name: str,
        status: str,
        active: bool,
        notes: str,
    ) -> Mapping[str, object] | None: ...

    async def delete_task(
        self,
        db: Database,
        /,
        *,
        id: int,
    ) -> Mapping[str, object] | None: ...


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


class TaskRepository:
    """Static query selection; request data is never interpolated into SQL."""

    def __init__(
        self,
        database: Database,
        queries: TaskQueryFacade,
        *,
        list_scope: ListScopeFactory | None = None,
    ) -> None:
        self._database = database
        self._queries = queries
        self._list_scope = list_scope or _unscoped_list

    async def list(self, query: ListQuery) -> Page:
        search = query.search or ""
        status = query.filters.get("status", "")
        async with self._list_scope():
            total = await self._queries.count_tasks(self._database, search=search, status=status)
            if query.order_by is None:
                rows = await self._queries.list_tasks_default(
                    self._database,
                    search=search,
                    status=status,
                    limit=query.limit,
                    offset=query.offset,
                )
            elif query.order_by == "name" and query.descending:
                rows = await self._queries.list_tasks_name_desc(
                    self._database,
                    search=search,
                    status=status,
                    limit=query.limit,
                    offset=query.offset,
                )
            elif query.order_by == "name":
                rows = await self._queries.list_tasks_name_asc(
                    self._database,
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
        row = await self._queries.get_task(self._database, id=task_id)
        return None if row is None else _task_record(row)

    async def create(self, values: Mapping[str, object]) -> Record:
        row = await self._queries.create_task(
            self._database,
            name=_string(values, "name"),
            status=_string(values, "status"),
            active=_boolean(values, "active"),
            notes=_string(values, "notes"),
        )
        return _task_record(row)

    async def update(
        self,
        object_id: str,
        values: Mapping[str, object],
    ) -> Record | None:
        task_id = _integer_id(object_id)
        if task_id is None:
            return None
        row = await self._queries.update_task(
            self._database,
            id=task_id,
            name=_string(values, "name"),
            status=_string(values, "status"),
            active=_boolean(values, "active"),
            notes=_string(values, "notes"),
        )
        return None if row is None else _task_record(row)

    async def delete(self, object_id: str) -> bool:
        task_id = _integer_id(object_id)
        return (
            task_id is not None
            and await self._queries.delete_task(self._database, id=task_id) is not None
        )


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
        ),
        page_size=10,
    )
