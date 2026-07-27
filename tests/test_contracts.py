from __future__ import annotations

import math

import pytest

from hayate_admin import (
    Actor,
    AdminAsset,
    AdminField,
    AdminResource,
    AdminValidationError,
    ListQuery,
    Page,
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
