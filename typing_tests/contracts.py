from __future__ import annotations

from collections.abc import Mapping
from typing import assert_type

from hayate import Context

from hayate_admin import AdminRepository, AdminRepositoryFactory, ListQuery, Page


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
