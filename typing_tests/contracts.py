from __future__ import annotations

from collections.abc import Mapping
from typing import assert_type

from hayate import Context

from hayate_admin import (
    AdminRepository,
    AdminRepositoryFactory,
    AdminResource,
    AuditHistoryPage,
    AuditHistoryReader,
    AuditHistoryReaderFactory,
    BulkActionHandler,
    BulkActionResult,
    ListQuery,
    Page,
)


class Repository:
    async def list(self, query: ListQuery) -> Page:
        return Page((), 0)

    async def get(self, object_id: str) -> Mapping[str, object] | None:
        return None

    async def create(self, values: Mapping[str, object]) -> Mapping[str, object]:
        return {"id": "1"}

    async def update(
        self,
        object_id: str,
        values: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        return None

    async def delete(self, object_id: str) -> bool:
        return False


repository: AdminRepository = Repository()
assert_type(repository, AdminRepository)


def repository_factory(context: Context) -> AdminRepository:
    return Repository()


factory: AdminRepositoryFactory = repository_factory
assert_type(factory, AdminRepositoryFactory)


async def bulk_handler(
    context: Context,
    repository: AdminRepository,
    object_ids: tuple[str, ...],
) -> BulkActionResult:
    return BulkActionResult(object_ids)


handler: BulkActionHandler = bulk_handler
assert_type(handler, BulkActionHandler)


async def history_reader(
    context: Context,
    resource: AdminResource,
    object_id: str,
    offset: int,
    limit: int,
) -> AuditHistoryPage:
    return AuditHistoryPage((), 0)


reader: AuditHistoryReader = history_reader
assert_type(reader, AuditHistoryReader)


def history_factory(context: Context) -> AuditHistoryReader:
    return history_reader


reader_factory: AuditHistoryReaderFactory = history_factory
assert_type(reader_factory, AuditHistoryReaderFactory)
