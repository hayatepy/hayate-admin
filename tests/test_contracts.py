from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from hayate_admin import (
    Actor,
    AdminAsset,
    AdminBulkAction,
    AdminCsvExport,
    AdminField,
    AdminInline,
    AdminRelationship,
    AdminResource,
    AdminSavedView,
    AdminValidationError,
    AuditEvent,
    AuditHistoryPage,
    BulkActionResult,
    CursorPage,
    ExportQuery,
    InlineCollection,
    InlineMutation,
    InlineMutationResult,
    ListQuery,
    Page,
    RelationshipChoice,
    RelationshipPage,
    RelationshipQuery,
)


class EmptyRepository:
    async def list(self, query):
        return Page((), 0)

    async def get(self, object_id):
        return None

    async def create(self, values):
        return {"id": "1"}

    async def update(self, object_id, values):
        return None

    async def delete(self, object_id):
        return False


@pytest.mark.parametrize("name", ["", "UPPER", "with-hyphen", "1starts_wrong", "x" * 64])
def test_field_names_are_safe_identifiers(name):
    with pytest.raises(ValueError, match="unsafe admin field name"):
        AdminField(name, "Unsafe")


def test_field_choice_and_filter_configuration_fails_closed():
    with pytest.raises(ValueError, match="select fields require choices"):
        AdminField("status", "Status", kind="select")
    with pytest.raises(ValueError, match="filters require"):
        AdminField("status", "Status", filterable=True)
    with pytest.raises(ValueError, match="unique"):
        AdminField(
            "status",
            "Status",
            kind="select",
            choices=(("open", "Open"), ("open", "Again")),
        )
    with pytest.raises(ValueError, match="read-only fields"):
        AdminField("id", "ID", read_only=True)


@pytest.mark.parametrize(
    ("field", "raw", "expected", "error"),
    [
        (AdminField("age", "Age", kind="integer"), "42", 42, None),
        (AdminField("age", "Age", kind="integer"), "4.2", None, "Enter an integer."),
        (AdminField("score", "Score", kind="number"), "1.5", 1.5, None),
        (
            AdminField("score", "Score", kind="number"),
            str(math.inf),
            None,
            "Enter a finite number.",
        ),
        (AdminField("email", "Email", kind="email"), "bad", None, "valid email"),
        (AdminField("day", "Day", kind="date"), "2026-07-27", "2026-07-27", None),
        (AdminField("day", "Day", kind="date"), "tomorrow", None, "valid date"),
        (
            AdminField("enabled", "Enabled", kind="checkbox", required=False),
            None,
            False,
            None,
        ),
    ],
)
def test_field_parser_is_bounded_and_typed(field, raw, expected, error):
    value, message = field.parse(raw)
    assert value == expected
    if error is None:
        assert message is None
    else:
        assert message is not None and error in message


def test_resource_rejects_unsafe_or_ambiguous_configuration():
    repository = EmptyRepository()
    id_field = AdminField("id", "ID", required=False, read_only=True)

    with pytest.raises(ValueError, match="unsafe admin resource slug"):
        AdminResource("Bad", "Bad", "Bad", (id_field,), repository)
    with pytest.raises(ValueError, match="field names must be unique"):
        AdminResource("items", "Items", "Item", (id_field, id_field), repository)
    with pytest.raises(ValueError, match="title_field"):
        AdminResource(
            "items",
            "Items",
            "Item",
            (id_field,),
            repository,
            title_field="name",
        )
    with pytest.raises(ValueError, match="shown in lists"):
        AdminResource(
            "items",
            "Items",
            "Item",
            (AdminField("id", "ID", required=False, read_only=True, list_display=False),),
            repository,
        )
    with pytest.raises(ValueError, match="page_size"):
        AdminResource("items", "Items", "Item", (id_field,), repository, page_size=101)


def test_bulk_action_and_result_contracts_fail_closed():
    async def handler(context, repository, object_ids):
        return BulkActionResult(object_ids)

    action = AdminBulkAction("close", "Close selected", "resource:change", handler, 10)
    assert action.max_selected == 10
    assert BulkActionResult(("1",), {"2": "Not found."}).succeeded == ("1",)

    with pytest.raises(ValueError, match="unsafe admin bulk action slug"):
        AdminBulkAction("Bad", "Bad", "resource:change", handler)
    with pytest.raises(ValueError, match="permission"):
        AdminBulkAction("export", "Export", "resource:view", handler)
    with pytest.raises(ValueError, match="max_selected"):
        AdminBulkAction("close", "Close", "resource:change", handler, 101)
    with pytest.raises(ValueError, match="unique"):
        BulkActionResult(("1", "1"))
    with pytest.raises(ValueError, match="overlap"):
        BulkActionResult(("1",), {"1": "Failed."})

    repository = EmptyRepository()
    id_field = AdminField("id", "ID", required=False, read_only=True)
    with pytest.raises(ValueError, match="bulk action slugs must be unique"):
        AdminResource(
            "items",
            "Items",
            "Item",
            (id_field,),
            repository,
            bulk_actions=(action, action),
        )


def test_relationship_and_inline_contracts_are_explicit_and_bounded():
    async def search(context, source, target, relationship, source_object_id, query):
        return RelationshipPage((RelationshipChoice("1", "Parent"),), 1)

    async def resolve(
        context,
        source,
        target,
        relationship,
        source_object_id,
        related_object_id,
    ):
        return RelationshipChoice(related_object_id, "Parent")

    async def read(context, parent, target, inline, parent_object_id, limit):
        return InlineCollection((), 0)

    async def mutate(context, parent, target, inline, parent_object_id, mutation):
        return InlineMutationResult(deleted=True)

    relationship = AdminRelationship(
        "parent_id",
        "items",
        "parent_name",
        search,
        resolve,
        max_choices=10,
    )
    inline = AdminInline(
        "children",
        "Children",
        "items",
        "parent_id",
        ("name",),
        read,
        mutate,
        max_items=5,
    )
    resource = AdminResource(
        "items",
        "Items",
        "Item",
        (
            AdminField("id", "ID", required=False, read_only=True),
            AdminField("name", "Name"),
            AdminField("parent_id", "Parent", required=False, list_display=False),
            AdminField(
                "parent_name",
                "Parent name",
                required=False,
                read_only=True,
            ),
        ),
        EmptyRepository(),
        relationships=(relationship,),
        inlines=(inline,),
    )
    assert resource.relationship_map["parent_id"] is relationship
    assert resource.inline_map["children"] is inline
    assert RelationshipQuery("parent", 0, 10).limit == 10
    assert InlineMutation("create", None, {"name": "Child"}).operation == "create"
    assert InlineMutationResult({"id": "1"}).deleted is False

    with pytest.raises(ValueError, match="max_choices"):
        AdminRelationship("parent_id", "items", "parent_name", search, resolve, 101)
    with pytest.raises(ValueError, match="complete bounded snapshot"):
        InlineCollection((), 1)
    with pytest.raises(ValueError, match="must not include values"):
        InlineMutation("delete", "1", {"name": "secret"})
    with pytest.raises(ValueError, match="one record or confirm"):
        InlineMutationResult()
    with pytest.raises(ValueError, match="display_field"):
        AdminResource(
            "items",
            "Items",
            "Item",
            (
                AdminField("id", "ID", required=False, read_only=True),
                AdminField("parent_id", "Parent", required=False),
            ),
            EmptyRepository(),
            relationships=(relationship,),
        )
    with pytest.raises(ValueError, match="bounded to 255"):
        AdminResource(
            "items",
            "Items",
            "Item",
            (
                AdminField("id", "ID", required=False, read_only=True),
                AdminField("parent_id", "Parent", required=False, max_length=256),
                AdminField(
                    "parent_name",
                    "Parent name",
                    required=False,
                    read_only=True,
                ),
            ),
            EmptyRepository(),
            relationships=(relationship,),
        )


def test_actor_asset_query_and_page_invariants():
    with pytest.raises(ValueError, match="actor id"):
        Actor("", "Admin")
    with pytest.raises(ValueError, match="same-origin"):
        AdminAsset("https://cdn.example/htmx.js", "sha384-YWJj")
    with pytest.raises(ValueError, match="SRI"):
        AdminAsset("/assets/htmx.js", "nope")
    with pytest.raises(ValueError, match="limit"):
        ListQuery(None, {}, None, False, 0, 101)
    with pytest.raises(ValueError, match="total"):
        Page((), -1)
    assert CursorPage(({"id": "1"},), "next").next_cursor == "next"
    with pytest.raises(ValueError, match="next cursor"):
        CursorPage((), "")
    with pytest.raises(ValueError, match="cannot include an offset"):
        ListQuery(None, {}, None, False, 1, 10, cursor="next")
    event = AuditEvent(
        datetime.now(UTC),
        "success",
        "resource:change",
        "items",
        "1",
        "operator",
    )
    assert AuditHistoryPage((event,), 1).items == (event,)
    with pytest.raises(ValueError, match="AuditEvent"):
        AuditHistoryPage((object(),), 1)
    with pytest.raises(ValueError, match="smaller"):
        AuditHistoryPage((event,), 0)


def test_saved_view_cursor_and_csv_contracts_are_explicit_and_bounded():
    async def export(context, repository, query):
        return ()

    repository = EmptyRepository()
    fields = (
        AdminField("id", "ID", required=False, read_only=True, sortable=True),
        AdminField("name", "Name", searchable=True),
        AdminField(
            "status",
            "Status",
            kind="select",
            choices=(("open", "Open"), ("closed", "Closed")),
            filterable=True,
        ),
    )
    view = AdminSavedView(
        "closed",
        "Closed",
        search="incident",
        filters={"status": "closed"},
        order_by="id",
        descending=True,
    )
    policy = AdminCsvExport(
        ("id", "name"),
        export,
        filename="items.csv",
        max_rows=50,
        max_bytes=2048,
    )
    configured = AdminResource(
        "items",
        "Items",
        "Item",
        fields,
        repository,
        pagination="cursor",
        saved_views=(view,),
        csv_export=policy,
    )
    assert configured.saved_view_map["closed"] is view
    assert configured.csv_export is policy
    assert ExportQuery("incident", {"status": "closed"}, "id", True, 51, "closed").limit == 51

    with pytest.raises(ValueError, match="saved view slug"):
        AdminSavedView("Bad", "Bad")
    with pytest.raises(ValueError, match="descending requires"):
        AdminSavedView("bad", "Bad", descending=True)
    with pytest.raises(ValueError, match="saved filters"):
        AdminResource(
            "items",
            "Items",
            "Item",
            fields,
            repository,
            saved_views=(AdminSavedView("bad", "Bad", filters={"status": "missing"}),),
        )
    with pytest.raises(ValueError, match="saved sort"):
        AdminResource(
            "items",
            "Items",
            "Item",
            fields,
            repository,
            saved_views=(AdminSavedView("bad", "Bad", order_by="name"),),
        )
    with pytest.raises(ValueError, match="CSV export fields"):
        AdminResource(
            "items",
            "Items",
            "Item",
            fields,
            repository,
            csv_export=AdminCsvExport(("secret",), export),
        )
    with pytest.raises(ValueError, match="filename"):
        AdminCsvExport(("id",), export, filename="../../items.csv")
    with pytest.raises(ValueError, match="max_rows"):
        AdminCsvExport(("id",), export, max_rows=10_001)
    with pytest.raises(ValueError, match="pagination"):
        AdminResource(
            "items",
            "Items",
            "Item",
            fields,
            repository,
            pagination="unknown",
        )


def test_public_contracts_reject_runtime_type_misconfiguration():
    repository = EmptyRepository()
    id_field = AdminField("id", "ID", required=False, read_only=True)

    with pytest.raises(ValueError, match="field kind"):
        AdminField("value", "Value", kind="unsupported")
    with pytest.raises(ValueError, match="string pairs"):
        AdminField("status", "Status", kind="select", choices=(("open",),))
    with pytest.raises(ValueError, match="field"):
        AdminResource("items", "Items", "Item", [id_field], repository)
    with pytest.raises(ValueError, match="repository"):
        AdminResource("items", "Items", "Item", (id_field,), object())
    with pytest.raises(ValueError, match="search"):
        ListQuery(42, {}, None, False, 0, 10)
    with pytest.raises(ValueError, match="filters"):
        ListQuery(None, {1: "bad"}, None, False, 0, 10)
    with pytest.raises(ValueError, match="items"):
        Page((object(),), 1)
    with pytest.raises(ValueError, match="bounded field messages"):
        AdminValidationError({"field": "x" * 501})
