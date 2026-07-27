from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, replace
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest
from hayate import Hayate

from hayate_admin import (
    Actor,
    AdminAction,
    AdminBulkAction,
    AdminField,
    AdminResource,
    AdminSite,
    AdminValidationError,
    AuditEvent,
    AuditHistoryPage,
    BulkActionResult,
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


def resource(
    repository: MemoryRepository,
    *,
    bulk_actions: tuple[AdminBulkAction, ...] = (),
) -> AdminResource:
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
        bulk_actions=bulk_actions,
        title_field="name",
        page_size=1,
    )


def make_app(
    repository: MemoryRepository,
    *,
    allowed: set[AdminAction] | None = None,
    bulk_actions: tuple[AdminBulkAction, ...] = (),
    history=None,
    history_factory=None,
):
    permitted = allowed or {
        "site:view",
        "resource:view",
        "resource:add",
        "resource:change",
        "resource:delete",
        "resource:bulk",
        "resource:history",
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
        history=history,
        history_factory=history_factory,
    )
    site.add(resource(repository, bulk_actions=bulk_actions))
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

    async def history(context, resource, object_id, offset, limit):
        return AuditHistoryPage((), 0)

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
    with pytest.raises(ValueError, match="at most one history"):
        AdminSite(
            title="Admin",
            allowed_origins={ORIGIN},
            authorize=authorize,
            audit=audit,
            history=history,
            history_factory=lambda context: history,
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


async def test_bulk_action_is_explicit_bounded_and_audited_per_object():
    repository = MemoryRepository()

    async def close_selected(context, admin_repository, object_ids):
        succeeded = []
        failed = {}
        for object_id in object_ids:
            record = repository.records.get(object_id)
            if record is None:
                failed[object_id] = "Record no longer exists."
            else:
                record["status"] = "closed"
                succeeded.append(object_id)
        return BulkActionResult(succeeded, failed)

    action = AdminBulkAction(
        "close",
        "Close selected",
        "resource:change",
        close_selected,
        max_selected=2,
    )
    app, _, _, audit_events = make_app(repository, bulk_actions=(action,))

    listing = await app.request("/admin/users")
    listing_body = await response_text(listing)
    assert 'name="selected"' in listing_body
    assert 'value="close"' in listing_body
    assert 'aria-label="Select &lt;script&gt;alert(1)&lt;/script&gt;"' in listing_body

    response = await app.request(
        "/admin/users/bulk",
        method="POST",
        headers=mutation_headers(),
        body=urlencode(
            [
                ("action", "close"),
                ("selected", "1"),
                ("selected", "missing"),
            ]
        ),
    )
    body = await response_text(response)
    assert response.status == 200
    assert "1 completed; 1 failed." in body
    assert "Record no longer exists." in body
    assert repository.records["1"]["status"] == "closed"
    assert [
        (event.phase, event.object_id, event.error_type, event.operation) for event in audit_events
    ] == [
        ("attempt", "1", None, "close"),
        ("attempt", "missing", None, "close"),
        ("success", "1", None, "close"),
        ("failure", "missing", "BulkActionFailed", "close"),
    ]

    rejected = await app.request(
        "/admin/users/bulk",
        method="POST",
        headers=mutation_headers(),
        body=urlencode(
            [
                ("action", "close"),
                ("selected", "1"),
                ("selected", "2"),
                ("selected", "3"),
            ]
        ),
    )
    assert rejected.status == 422
    assert "Select at most 2 records." in await response_text(rejected)


async def test_bulk_action_checks_every_object_permission_before_callback():
    repository = MemoryRepository()
    callback_calls = []
    audit_events: list[AuditEvent] = []

    async def handler(context, admin_repository, object_ids):
        callback_calls.append(object_ids)
        return BulkActionResult(object_ids)

    async def authorize(context, action, admin_resource, object_id):
        if action == "resource:change" and object_id == "2":
            return None
        return Actor("operator-1", "Operator")

    async def audit(event):
        audit_events.append(event)

    app = Hayate()
    site = AdminSite(
        title="Operations",
        allowed_origins={ORIGIN},
        authorize=authorize,
        audit=audit,
    )
    site.add(
        resource(
            repository,
            bulk_actions=(AdminBulkAction("close", "Close selected", "resource:change", handler),),
        )
    )
    site.register(app)

    response = await app.request(
        "/admin/users/bulk",
        method="POST",
        headers=mutation_headers(),
        body=urlencode(
            [
                ("action", "close"),
                ("selected", "1"),
                ("selected", "2"),
            ]
        ),
    )
    assert response.status == 403
    assert callback_calls == []
    assert [
        (event.phase, event.object_id, event.error_type, event.operation) for event in audit_events
    ] == [("failure", "2", "AuthorizationDenied", "close")]


async def test_bulk_action_rejects_unknown_cross_origin_and_incomplete_results():
    repository = MemoryRepository()
    callback_calls = []

    async def incomplete(context, admin_repository, object_ids):
        callback_calls.append(object_ids)
        return BulkActionResult(object_ids[:1])

    action = AdminBulkAction("close", "Close selected", "resource:change", incomplete)
    app, _, _, audit_events = make_app(repository, bulk_actions=(action,))

    unknown = await app.request(
        "/admin/users/bulk",
        method="POST",
        headers=mutation_headers(),
        body=urlencode({"action": "unregistered", "selected": "1"}),
    )
    assert unknown.status == 422
    assert callback_calls == []

    cross_origin = await app.request(
        "/admin/users/bulk",
        method="POST",
        headers=mutation_headers(origin="https://evil.example"),
        body=urlencode({"action": "close", "selected": "1"}),
    )
    assert cross_origin.status == 403
    assert callback_calls == []

    incomplete_result = await app.request(
        "/admin/users/bulk",
        method="POST",
        headers=mutation_headers(),
        body=urlencode(
            [
                ("action", "close"),
                ("selected", "1"),
                ("selected", "2"),
            ]
        ),
    )
    assert incomplete_result.status == 500
    assert callback_calls == [("1", "2")]
    assert [event.error_type for event in audit_events[-2:]] == ["ValueError", "ValueError"]


async def test_object_history_is_separately_authorized_bounded_and_escaped():
    repository = MemoryRepository()
    reader_calls = []
    occurred_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

    async def history(context, admin_resource, object_id, offset, limit):
        reader_calls.append((admin_resource.slug, object_id, offset, limit))
        return AuditHistoryPage(
            (
                AuditEvent(
                    occurred_at,
                    "failure",
                    "resource:bulk",
                    "users",
                    "1",
                    "<operator>",
                    "BulkActionFailed",
                    "close",
                ),
            ),
            1,
        )

    app, _, _, _ = make_app(repository, history=history)
    detail = await app.request("/admin/users/object/1")
    assert ">History</a>" in await response_text(detail)

    response = await app.request("/admin/users/object/1/history")
    body = await response_text(response)
    assert response.status == 200
    assert "resource:bulk / close" in body
    assert "&lt;operator&gt;" in body
    assert "<operator>" not in body
    assert "BulkActionFailed" in body
    assert "submitted values are not recorded" in body
    assert reader_calls == [("users", "1", 0, 50)]

    invalid_page = await app.request("/admin/users/object/1/history?page=0")
    assert invalid_page.status == 400
    assert len(reader_calls) == 1

    denied_app, _, _, _ = make_app(
        repository,
        allowed={"site:view", "resource:view"},
        history=history,
    )
    denied = await denied_app.request("/admin/users/object/1/history")
    assert denied.status == 403
    assert len(reader_calls) == 1


async def test_object_history_rejects_cross_object_reader_results():
    repository = MemoryRepository()

    async def mismatched(context, admin_resource, object_id, offset, limit):
        return AuditHistoryPage(
            (
                AuditEvent(
                    datetime.now(UTC),
                    "success",
                    "resource:change",
                    "users",
                    "2",
                    "operator",
                ),
            ),
            1,
        )

    app, _, _, _ = make_app(repository, history=mismatched)
    response = await app.request("/admin/users/object/1/history")
    assert response.status == 500


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


async def test_request_scoped_repository_audit_and_history_factories_use_context_bindings():
    repository = MemoryRepository()
    binding = object()
    repository_bindings = []
    audit_bindings = []
    history_bindings = []
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

    def history_factory(context):
        history_bindings.append(context.env["database"])

        async def history(context, admin_resource, object_id, offset, limit):
            return AuditHistoryPage((), 0)

        return history

    app = Hayate(env={"database": binding})
    site = AdminSite(
        title="Operations",
        allowed_origins={ORIGIN},
        authorize=authorize,
        audit_factory=audit_factory,
        history_factory=history_factory,
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
    history = await app.request("/admin/users/object/3/history")
    assert history.status == 200
    assert repository_bindings == [binding, binding]
    assert audit_bindings == [binding, binding]
    assert history_bindings == [binding]
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
