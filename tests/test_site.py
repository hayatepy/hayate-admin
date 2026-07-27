from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, replace
from urllib.parse import urlencode

import pytest
from hayate import Hayate

from hayate_admin import (
    Actor,
    AdminAction,
    AdminField,
    AdminResource,
    AdminSite,
    AdminValidationError,
    AuditEvent,
    ListQuery,
    Page,
)

ORIGIN = "https://admin.example"


class MemoryRepository:
    def __init__(self) -> None:
        self.records = {
            "1": {
                "id": "1",
                "name": "<script>alert(1)</script>",
                "email": "first@example.com",
                "status": "open",
                "active": True,
                "notes": "safe",
            },
            "2": {
                "id": "2",
                "name": "Second",
                "email": "second@example.com",
                "status": "closed",
                "active": False,
                "notes": "",
            },
        }
        self.queries: list[ListQuery] = []
        self.created: list[Mapping[str, object]] = []
        self.updated: list[tuple[str, Mapping[str, object]]] = []
        self.deleted: list[str] = []
        self.create_error: AdminValidationError | None = None

    async def list(self, query: ListQuery) -> Page:
        self.queries.append(query)
        records = list(self.records.values())
        if query.search:
            needle = query.search.casefold()
            records = [
                record
                for record in records
                if needle in str(record["name"]).casefold()
                or needle in str(record["email"]).casefold()
            ]
        for name, value in query.filters.items():
            records = [record for record in records if str(record[name]) == value]
        if query.order_by:
            records.sort(key=lambda record: str(record[query.order_by]), reverse=query.descending)
        total = len(records)
        records = records[query.offset : query.offset + query.limit]
        return Page(records, total)

    async def get(self, object_id: str):
        return self.records.get(object_id)

    async def create(self, values: Mapping[str, object]):
        if self.create_error is not None:
            raise self.create_error
        self.created.append(values)
        object_id = str(len(self.records) + 1)
        record = {"id": object_id, "notes": "", **values}
        self.records[object_id] = record
        return record

    async def update(self, object_id: str, values: Mapping[str, object]):
        record = self.records.get(object_id)
        if record is None:
            return None
        self.updated.append((object_id, values))
        record.update(values)
        return record

    async def delete(self, object_id: str) -> bool:
        self.deleted.append(object_id)
        return self.records.pop(object_id, None) is not None


def resource(repository: MemoryRepository) -> AdminResource:
    return AdminResource(
        "users",
        "Users",
        "User",
        (
            AdminField(
                "id",
                "ID",
                required=False,
                read_only=True,
                sortable=True,
            ),
            AdminField("name", "Name", searchable=True, sortable=True),
            AdminField("email", "Email", kind="email", searchable=True, sortable=True),
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
                max_length=1000,
            ),
        ),
        repository,
        title_field="name",
        page_size=1,
    )


def make_app(
    repository: MemoryRepository,
    *,
    allowed: set[AdminAction] | None = None,
):
    permitted = allowed or {
        "site:view",
        "resource:view",
        "resource:add",
        "resource:change",
        "resource:delete",
    }
    authorization_calls = []
    audit_events: list[AuditEvent] = []

    async def authorize(context, action, admin_resource, object_id):
        authorization_calls.append(
            (action, None if admin_resource is None else admin_resource.slug)
        )
        if action not in permitted:
            return None
        return Actor("operator-1", "Operator <One>")

    async def audit(event):
        audit_events.append(event)

    app = Hayate()
    site = AdminSite(
        title="Operations <Admin>",
        allowed_origins={ORIGIN},
        authorize=authorize,
        audit=audit,
    )
    site.add(resource(repository))
    site.register(app)
    return app, site, authorization_calls, audit_events


async def response_text(response) -> str:
    return await response.text()


def mutation_headers(*, origin: str = ORIGIN, htmx: bool = False) -> dict[str, str]:
    headers = {
        "content-type": "application/x-www-form-urlencoded",
        "origin": origin,
        "sec-fetch-site": "same-origin" if origin == ORIGIN else "cross-site",
    }
    if htmx:
        headers["hx-request"] = "true"
    return headers


def valid_form(**overrides: str) -> str:
    values = {
        "name": "Third",
        "email": "third@example.com",
        "status": "open",
        "active": "true",
        "notes": "hello",
        **overrides,
    }
    return urlencode(values)


def test_site_configuration_and_registration_fail_closed():
    async def authorize(context, action, admin_resource, object_id):
        return None

    async def audit(event):
        pass

    with pytest.raises(ValueError, match="exactly one audit"):
        AdminSite(title="Admin", allowed_origins={ORIGIN}, authorize=authorize)
    with pytest.raises(ValueError, match="exactly one audit"):
        AdminSite(
            title="Admin",
            allowed_origins={ORIGIN},
            authorize=authorize,
            audit=audit,
            audit_factory=lambda context: audit,
        )
    with pytest.raises(ValueError, match="allowed_origins"):
        AdminSite(title="Admin", allowed_origins=set(), authorize=authorize, audit=audit)
    with pytest.raises(ValueError, match="invalid admin allowed origin"):
        AdminSite(
            title="Admin",
            allowed_origins={"https://example.com/path"},
            authorize=authorize,
            audit=audit,
        )

    site = AdminSite(
        title="Admin",
        allowed_origins={ORIGIN},
        authorize=authorize,
        audit=audit,
    )
    with pytest.raises(RuntimeError, match="at least one resource"):
        site.register(Hayate())


async def test_anonymous_site_and_resource_access_is_forbidden():
    repository = MemoryRepository()
    app, _, _, _ = make_app(repository, allowed={"resource:view"})
    response = await app.request("/admin")
    assert response.status == 403

    app, _, _, _ = make_app(repository, allowed={"site:view"})
    response = await app.request("/admin/users")
    assert response.status == 403


async def test_list_query_is_allowlisted_bounded_and_safely_escaped():
    repository = MemoryRepository()
    app, _, _, _ = make_app(repository)
    response = await app.request(
        "/admin/users?q=script&filter_status=open&sort=name&direction=desc&page=1"
    )
    body = await response_text(response)

    assert response.status == 200
    assert "<!doctype html>" in body
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "Operator &lt;One&gt;" in body
    assert response.headers.get("cache-control") == "no-store"
    assert "frame-ancestors 'none'" in (response.headers.get("content-security-policy") or "")
    assert "HX-Request" in (response.headers.get("vary") or "")
    assert repository.queries[-1] == ListQuery(
        search="script",
        filters={"status": "open"},
        order_by="name",
        descending=True,
        offset=0,
        limit=1,
    )

    await app.request(
        "/admin/users?sort=DROP%20TABLE%20users&filter_status=not-allowed&direction=desc"
    )
    assert repository.queries[-1].order_by is None
    assert repository.queries[-1].filters == {}


async def test_htmx_list_returns_only_the_fragment_and_complete_vary():
    repository = MemoryRepository()
    app, _, _, _ = make_app(repository)
    response = await app.request("/admin/users", headers={"hx-request": "true"})
    body = await response_text(response)
    assert body.startswith('<main id="hayate-admin"')
    assert "<!doctype html>" not in body
    assert response.headers.get("vary") == (
        "HX-Request, HX-History-Restore-Request, HX-Request-Type"
    )


async def test_invalid_page_is_a_problem_response_without_repository_access():
    repository = MemoryRepository()
    app, _, _, _ = make_app(repository)
    response = await app.request("/admin/users?page=not-a-number")
    assert response.status == 400
    assert repository.queries == []


async def test_cross_site_mutation_is_rejected_before_authorization_or_storage():
    repository = MemoryRepository()
    app, _, authorization_calls, audit_events = make_app(repository)
    response = await app.request(
        "/admin/users/create",
        method="POST",
        headers=mutation_headers(origin="https://evil.example"),
        body=valid_form(),
    )
    assert response.status == 403
    assert repository.created == []
    assert authorization_calls == []
    assert [(event.phase, event.error_type) for event in audit_events] == [
        ("failure", "CrossSiteRequest")
    ]


async def test_origin_is_required_even_without_fetch_metadata():
    repository = MemoryRepository()
    app, _, _, audit_events = make_app(repository)
    response = await app.request(
        "/admin/users/create",
        method="POST",
        headers={"content-type": "application/x-www-form-urlencoded"},
        body=valid_form(),
    )
    assert response.status == 403
    assert audit_events[-1].error_type == "InvalidOrigin"


async def test_form_validation_preserves_values_and_audit_redacts_them():
    repository = MemoryRepository()
    app, _, _, audit_events = make_app(repository)
    secret = "submitted-secret-marker"
    response = await app.request(
        "/admin/users/create",
        method="POST",
        headers=mutation_headers(),
        body=urlencode(
            {
                "name": secret,
                "email": "invalid",
                "status": "not-a-choice",
                "unexpected": secret,
            }
        ),
    )
    body = await response_text(response)
    assert response.status == 422
    assert secret in body
    assert "Enter a valid email address." in body
    assert "Select a valid choice." in body
    assert "unexpected field" in body
    assert repository.created == []
    assert [(event.phase, event.error_type) for event in audit_events] == [
        ("attempt", None),
        ("failure", "ValidationError"),
    ]
    assert all(field.name != "values" for field in fields(AuditEvent))
    assert secret not in repr(audit_events)


async def test_repository_validation_is_rendered_without_exposing_unknown_fields():
    repository = MemoryRepository()
    repository.create_error = AdminValidationError(
        {"name": "Already exists.", "database_secret": "must not become a field name"}
    )
    app, _, _, audit_events = make_app(repository)
    response = await app.request(
        "/admin/users/create",
        method="POST",
        headers=mutation_headers(),
        body=valid_form(),
    )
    body = await response_text(response)
    assert response.status == 422
    assert "Already exists." in body
    assert "database_secret" not in body
    assert audit_events[-1].error_type == "AdminValidationError"


async def test_create_edit_and_delete_with_audited_post_redirect_get():
    repository = MemoryRepository()
    app, _, _, audit_events = make_app(repository)

    created = await app.request(
        "/admin/users/create",
        method="POST",
        headers=mutation_headers(),
        body=valid_form(),
    )
    assert created.status == 303
    assert created.headers.get("location") == "/admin/users/object/3"
    assert dict(repository.created[-1]) == {
        "name": "Third",
        "email": "third@example.com",
        "status": "open",
        "active": True,
        "notes": "hello",
    }

    detail = await app.request("/admin/users/object/3")
    assert detail.status == 200
    assert "Third" in await response_text(detail)

    edited = await app.request(
        "/admin/users/object/3/edit",
        method="POST",
        headers=mutation_headers(htmx=True),
        body=valid_form(name="Updated", active=""),
    )
    assert edited.status == 204
    assert edited.headers.get("hx-redirect") == "/admin/users/object/3"
    assert repository.records["3"]["name"] == "Updated"

    confirmation = await app.request("/admin/users/object/3/delete")
    assert confirmation.status == 200
    assert "cannot be undone" in await response_text(confirmation)

    deleted = await app.request(
        "/admin/users/object/3/delete",
        method="POST",
        headers=mutation_headers(),
        body="",
    )
    assert deleted.status == 303
    assert deleted.headers.get("location") == "/admin/users"
    assert "3" not in repository.records
    assert [
        (event.phase, event.action, event.object_id, event.actor_id) for event in audit_events
    ] == [
        ("attempt", "resource:add", None, "operator-1"),
        ("success", "resource:add", "3", "operator-1"),
        ("attempt", "resource:change", "3", "operator-1"),
        ("success", "resource:change", "3", "operator-1"),
        ("attempt", "resource:delete", "3", "operator-1"),
        ("success", "resource:delete", "3", "operator-1"),
    ]


async def test_denied_mutation_is_audited_without_touching_repository():
    repository = MemoryRepository()
    app, _, _, audit_events = make_app(
        repository,
        allowed={"site:view", "resource:view"},
    )
    response = await app.request(
        "/admin/users/object/1/delete",
        method="POST",
        headers=mutation_headers(),
        body="",
    )
    assert response.status == 403
    assert repository.deleted == []
    assert audit_events[-1].error_type == "AuthorizationDenied"
    assert audit_events[-1].actor_id is None


async def test_attempt_audit_failure_stops_mutation_before_storage():
    repository = MemoryRepository()

    async def authorize(context, action, admin_resource, object_id):
        return Actor("operator-1", "Operator")

    async def failing_audit(event):
        if event.phase == "attempt":
            raise RuntimeError("audit unavailable")

    app = Hayate()
    site = AdminSite(
        title="Operations",
        allowed_origins={ORIGIN},
        authorize=authorize,
        audit=failing_audit,
    )
    site.add(resource(repository))
    site.register(app)

    response = await app.request(
        "/admin/users/create",
        method="POST",
        headers=mutation_headers(),
        body=valid_form(),
    )
    assert response.status == 500
    assert repository.created == []


async def test_request_scoped_repository_and_audit_factories_use_context_bindings():
    repository = MemoryRepository()
    binding = object()
    repository_bindings = []
    audit_bindings = []
    audit_events: list[AuditEvent] = []

    async def authorize(context, action, admin_resource, object_id):
        return Actor("operator-1", "Operator")

    def repository_factory(context):
        repository_bindings.append(context.env["database"])
        return repository

    def audit_factory(context):
        audit_bindings.append(context.env["database"])

        async def audit(event):
            audit_events.append(event)

        return audit

    app = Hayate(env={"database": binding})
    site = AdminSite(
        title="Operations",
        allowed_origins={ORIGIN},
        authorize=authorize,
        audit_factory=audit_factory,
    )
    site.add(replace(resource(repository), repository=repository_factory))
    site.register(app)

    listed = await app.request("/admin/users")
    assert listed.status == 200
    created = await app.request(
        "/admin/users/create",
        method="POST",
        headers=mutation_headers(),
        body=valid_form(),
    )
    assert created.status == 303
    assert repository_bindings == [binding, binding]
    assert audit_bindings == [binding, binding]
    assert [event.phase for event in audit_events] == ["attempt", "success"]


async def test_form_body_limit_and_media_type_are_enforced():
    repository = MemoryRepository()
    app, _, _, audit_events = make_app(repository)
    oversized = "name=" + "x" * (65 * 1024)
    response = await app.request(
        "/admin/users/create",
        method="POST",
        headers=mutation_headers(),
        body=oversized,
    )
    assert response.status == 413
    assert audit_events[-1].error_type == "InvalidForm"

    response = await app.request(
        "/admin/users/create",
        method="POST",
        headers={"content-type": "application/json", "origin": ORIGIN},
        body="{}",
    )
    assert response.status == 415
