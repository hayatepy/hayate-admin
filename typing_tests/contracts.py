from __future__ import annotations

from collections.abc import Mapping
from typing import assert_type

from hayate import Context

from hayate_admin import (
    AdminInline,
    AdminRelationship,
    AdminRepository,
    AdminRepositoryFactory,
    AdminResource,
    AuditHistoryPage,
    AuditHistoryReader,
    AuditHistoryReaderFactory,
    BulkActionHandler,
    BulkActionResult,
    CsvExportHandler,
    CursorPage,
    ExportQuery,
    InlineCollection,
    InlineMutation,
    InlineMutationResult,
    InlineMutator,
    InlineReader,
    ListQuery,
    Page,
    RelationshipChoice,
    RelationshipPage,
    RelationshipQuery,
    RelationshipResolver,
    RelationshipSearcher,
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


async def csv_export(
    context: Context,
    repository: AdminRepository,
    query: ExportQuery,
) -> tuple[Mapping[str, object], ...]:
    return ()


export_handler: CsvExportHandler = csv_export
assert_type(export_handler, CsvExportHandler)


class CursorRepository:
    async def list(self, query: ListQuery) -> CursorPage:
        return CursorPage((), None)

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


cursor_repository: AdminRepository = CursorRepository()
assert_type(cursor_repository, AdminRepository)


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


async def relationship_searcher(
    context: Context,
    source_resource: AdminResource,
    target_resource: AdminResource,
    relationship: AdminRelationship,
    source_object_id: str | None,
    query: RelationshipQuery,
) -> RelationshipPage:
    return RelationshipPage((), 0)


relationship_search: RelationshipSearcher = relationship_searcher
assert_type(relationship_search, RelationshipSearcher)


async def relationship_resolver(
    context: Context,
    source_resource: AdminResource,
    target_resource: AdminResource,
    relationship: AdminRelationship,
    source_object_id: str | None,
    related_object_id: str,
) -> RelationshipChoice | None:
    return None


relationship_resolve: RelationshipResolver = relationship_resolver
assert_type(relationship_resolve, RelationshipResolver)


async def inline_reader(
    context: Context,
    parent_resource: AdminResource,
    target_resource: AdminResource,
    inline: AdminInline,
    parent_object_id: str,
    limit: int,
) -> InlineCollection:
    return InlineCollection((), 0)


read_inline: InlineReader = inline_reader
assert_type(read_inline, InlineReader)


async def inline_mutator(
    context: Context,
    parent_resource: AdminResource,
    target_resource: AdminResource,
    inline: AdminInline,
    parent_object_id: str,
    mutation: InlineMutation,
) -> InlineMutationResult:
    return InlineMutationResult(deleted=True)


mutate_inline: InlineMutator = inline_mutator
assert_type(mutate_inline, InlineMutator)
