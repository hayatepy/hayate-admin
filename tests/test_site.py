from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from dataclasses import fields, replace
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest
from hayate import Hayate

from hayate_admin import (
    Actor,
    AdminAction,
    AdminBranding,
    AdminBulkAction,
    AdminCsvExport,
    AdminCursorError,
    AdminField,
    AdminInline,
    AdminMessages,
    AdminRelationship,
    AdminResource,
    AdminSavedView,
    AdminSite,
    AdminTheme,
    AdminValidationError,
    AuditEvent,
    AuditHistoryPage,
    BulkActionResult,
    CursorPage,
    ExportQuery,
    InlineCollection,
    InlineMutationResult,
    ListQuery,
    Page,
    RelationshipChoice,
    RelationshipPage,
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


class CursorMemoryRepository(MemoryRepository):
    async def list(self, query: ListQuery) -> CursorPage:
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
        try:
            start = 0 if query.cursor is None else int(query.cursor)
        except ValueError as error:
            raise AdminCursorError from error
        items = records[start : start + query.limit]
        next_offset = start + len(items)
        next_cursor = None if next_offset >= len(records) else str(next_offset)
        return CursorPage(items, next_cursor)


def resource(
    repository: MemoryRepository,
    *,
    bulk_actions: tuple[AdminBulkAction, ...] = (),
    pagination: str = "offset",
    saved_views: tuple[AdminSavedView, ...] = (),
    csv_export: AdminCsvExport | None = None,
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
        pagination=pagination,
        saved_views=saved_views,
        csv_export=csv_export,
    )


def make_app(
    repository: MemoryRepository,
    *,
    allowed: set[AdminAction] | None = None,
    bulk_actions: tuple[AdminBulkAction, ...] = (),
    history=None,
    history_factory=None,
    pagination: str = "offset",
    saved_views: tuple[AdminSavedView, ...] = (),
    csv_export: AdminCsvExport | None = None,
    denied_export_ids: frozenset[str] = frozenset(),
    messages: AdminMessages | None = None,
    branding: AdminBranding | None = None,
):
    permitted = allowed or {
        "site:view",
        "resource:view",
        "resource:add",
        "resource:change",
        "resource:delete",
        "resource:bulk",
        "resource:export",
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
        if action == "resource:export" and object_id in denied_export_ids:
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
        messages=messages or AdminMessages(),
        branding=branding,
    )
    site.add(
        resource(
            repository,
            bulk_actions=bulk_actions,
            pagination=pagination,
            saved_views=saved_views,
            csv_export=csv_export,
        )
    )
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


async def test_localization_branding_and_accessibility_policy_are_site_scoped():
    repository = MemoryRepository()
    messages = AdminMessages(
        locale="ja",
        overrides={
            "accessibility.skip_to_main": "本文へ移動",
            "accessibility.signed_in": "ログイン中の管理者",
            "list.search": "検索",
            "list.apply": "適用",
            "list.matching.other": "{count}件",
            "action.view": "表示",
            "action.edit": "編集",
            "action.delete": "削除",
        },
    )
    branding = AdminBranding(
        wordmark="<Hayate 運用>",
        theme=AdminTheme(density="compact"),
    )
    app, _, _, _ = make_app(
        repository,
        messages=messages,
        branding=branding,
    )
    response = await app.request("/admin/users")
    body = await response_text(response)
    policy = response.headers.get("content-security-policy") or ""

    assert response.status == 200
    assert '<html lang="ja">' in body
    assert ">本文へ移動</a>" in body
    assert 'aria-label="ログイン中の管理者"' in body
    assert "<Hayate 運用>" not in body
    assert "&lt;Hayate 運用&gt;" in body
    assert "<label>検索" in body
    assert 'class="hayate-admin-density-compact"' in body
    assert "@media(prefers-reduced-motion:reduce)" in body
    assert "style-src 'sha256-" in policy
    assert "'unsafe-inline'" not in policy


async def test_saved_views_apply_only_registered_allowlisted_controls():
    repository = MemoryRepository()
    saved_view = AdminSavedView(
        "closed-by-name",
        "Closed by name",
        filters={"status": "closed"},
        order_by="name",
    )
    app, _, _, _ = make_app(repository, saved_views=(saved_view,))

    response = await app.request("/admin/users?view=closed-by-name")
    body = await response_text(response)
    assert response.status == 200
    assert "Second" in body
    assert "<script>alert(1)</script>" not in body
    assert 'aria-label="Saved views"' in body
    assert 'aria-current="page"' in body
    assert 'type="hidden" name="view" value="closed-by-name"' in body
    assert repository.queries[-1] == ListQuery(
        search=None,
        filters={"status": "closed"},
        order_by="name",
        descending=False,
        offset=0,
        limit=1,
        saved_view="closed-by-name",
    )

    overridden = await app.request("/admin/users?view=closed-by-name&filter_status=open")
    assert overridden.status == 200
    assert repository.queries[-1].filters == {"status": "open"}

    fragment = await app.request(
        "/admin/users?view=closed-by-name",
        headers={"hx-request": "true"},
    )
    fragment_body = await response_text(fragment)
    assert fragment.status == 200
    assert fragment_body.startswith('<main id="hayate-admin"')
    assert "<!doctype html>" not in fragment_body

    calls = len(repository.queries)
    unknown = await app.request("/admin/users?view=unregistered")
    assert unknown.status == 400
    assert len(repository.queries) == calls


async def test_cursor_pagination_is_opaque_query_bound_and_forward_only():
    repository = CursorMemoryRepository()
    app, _, _, _ = make_app(repository, pagination="cursor")

    first = await app.request("/admin/users")
    first_body = await response_text(first)
    assert first.status == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in first_body
    assert 'aria-label="Cursor pagination"' in first_body
    match = re.search(r"[?&]cursor=([A-Za-z0-9_-]+)", first_body)
    assert match is not None
    token = match.group(1)
    assert token != "1"

    second = await app.request(f"/admin/users?cursor={token}")
    second_body = await response_text(second)
    assert second.status == 200
    assert "Second" in second_body
    assert repository.queries[-1].cursor == "1"
    assert "End of results" in second_body
    assert ">First</a>" in second_body

    cross_query = await app.request(f"/admin/users?cursor={token}&q=Second")
    assert cross_query.status == 400
    offset = await app.request("/admin/users?page=2")
    assert offset.status == 400
    malformed = await app.request("/admin/users?cursor=not%2Ba%2Ftoken")
    assert malformed.status == 400

    padding = "=" * (-len(token) % 4)
    payload = json.loads(base64.urlsafe_b64decode(token + padding))
    payload["r"] = "accounts"
    cross_resource_token = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    cross_resource = await app.request(f"/admin/users?cursor={cross_resource_token}")
    assert cross_resource.status == 400

    payload["r"] = "users"
    payload["c"] = "unsupported"
    unsupported_token = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    unsupported = await app.request(f"/admin/users?cursor={unsupported_token}")
    assert unsupported.status == 400
    oversized = await app.request(f"/admin/users?cursor={'a' * 4097}")
    assert oversized.status == 400


async def test_csv_export_is_separately_authorized_bounded_and_spreadsheet_safe():
    repository = MemoryRepository()
    repository.records["1"]["name"] = "=2+2"
    queries: list[ExportQuery] = []

    async def export(context, admin_repository, query):
        assert admin_repository is repository
        queries.append(query)
        return tuple(repository.records.values())

    policy = AdminCsvExport(
        ("name", "status"),
        export,
        filename="users.csv",
        max_rows=2,
        max_bytes=2048,
    )
    app, _, _, audit_events = make_app(repository, csv_export=policy)

    listing = await app.request("/admin/users?filter_status=open")
    listing_body = await response_text(listing)
    assert 'href="/admin/users/export.csv?filter_status=open"' in listing_body
    assert 'hx-get="/admin/users/export.csv' not in listing_body

    response = await app.request("/admin/users/export.csv?sort=name&direction=desc")
    body = await response_text(response)
    assert response.status == 200
    assert response.headers.get("content-type") == "text/csv; charset=utf-8"
    assert response.headers.get("content-disposition") == 'attachment; filename="users.csv"'
    assert body.splitlines()[0] == "Name,Status"
    assert "'=2+2" in body
    assert "first@example.com" not in body
    assert queries == [ExportQuery(None, {}, "name", True, 3)]
    assert [
        (event.phase, event.action, event.operation, event.object_id) for event in audit_events
    ] == [
        ("attempt", "resource:export", "csv", None),
        ("success", "resource:export", "csv", None),
    ]
    assert "=2+2" not in repr(audit_events)
    cross_site = await app.request(
        "/admin/users/export.csv",
        headers={"sec-fetch-site": "cross-site"},
    )
    assert cross_site.status == 403
    assert audit_events[-1].error_type == "CrossSiteRequest"

    denied_app, _, _, denied_events = make_app(
        repository,
        allowed={"site:view", "resource:view"},
        csv_export=policy,
    )
    denied = await denied_app.request("/admin/users/export.csv")
    assert denied.status == 403
    assert denied_events[-1].error_type == "AuthorizationDenied"

    object_denied_app, _, _, object_denied_events = make_app(
        repository,
        csv_export=policy,
        denied_export_ids=frozenset({"2"}),
    )
    object_denied = await object_denied_app.request("/admin/users/export.csv")
    assert object_denied.status == 403
    assert object_denied_events[-1].object_id == "2"
    assert object_denied_events[-1].error_type == "AuthorizationDenied"


async def test_csv_export_rejects_page_controls_row_overflow_and_byte_overflow():
    repository = MemoryRepository()

    async def export(context, admin_repository, query):
        return tuple(repository.records.values())

    row_policy = AdminCsvExport(
        ("name",),
        export,
        max_rows=1,
        max_bytes=2048,
    )
    app, _, _, audit_events = make_app(repository, csv_export=row_policy)
    invalid_query = await app.request("/admin/users/export.csv?page=1")
    assert invalid_query.status == 400
    row_overflow = await app.request("/admin/users/export.csv")
    assert row_overflow.status == 413
    assert audit_events[-1].error_type == "ExportRowLimitExceeded"

    repository.records = {
        "1": {
            "id": "1",
            "name": "x" * 2000,
            "email": "first@example.com",
            "status": "open",
            "active": True,
            "notes": "",
        }
    }
    byte_policy = AdminCsvExport(
        ("name",),
        export,
        max_rows=1,
        max_bytes=1024,
    )
    byte_app, _, _, byte_events = make_app(repository, csv_export=byte_policy)
    byte_overflow = await byte_app.request("/admin/users/export.csv")
    assert byte_overflow.status == 413
    assert byte_events[-1].error_type == "ExportByteLimitExceeded"


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
    assert "Run bulk action / close" in body
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


class SmallRepository:
    def __init__(self, records):
        self.records = records
        self.created: list[Mapping[str, object]] = []

    async def list(self, query):
        return Page(tuple(self.records.values()), len(self.records))

    async def get(self, object_id):
        return self.records.get(object_id)

    async def create(self, values):
        self.created.append(values)
        object_id = str(len(self.records) + 1)
        record = {"id": object_id, **values}
        self.records[object_id] = record
        return record

    async def update(self, object_id, values):
        record = self.records.get(object_id)
        if record is None:
            return None
        record.update(values)
        return record

    async def delete(self, object_id):
        return self.records.pop(object_id, None) is not None


async def test_relationship_choices_are_bounded_resolved_and_preloaded_without_n_plus_one():
    class TaskRepository(SmallRepository):
        async def create(self, values):
            record = await super().create(values)
            record["project_name"] = "Public project"
            return record

    project_repository = SmallRepository(
        {
            "p1": {"id": "p1", "name": "Public project"},
            "secret": {"id": "secret", "name": "Secret tenant project"},
        }
    )
    task_repository = TaskRepository(
        {
            "t1": {
                "id": "t1",
                "name": "Existing task",
                "project_id": "p1",
                "project_name": "Public project",
            }
        }
    )
    search_calls = []
    resolve_calls = []

    async def search(context, source, target, relationship, source_object_id, query):
        search_calls.append((source_object_id, query))
        choices = (RelationshipChoice("p1", "Public project"),)
        if query.search and "public" not in query.search.casefold():
            choices = ()
        return RelationshipPage(choices, len(choices))

    async def resolve(
        context,
        source,
        target,
        relationship,
        source_object_id,
        related_object_id,
    ):
        resolve_calls.append((source_object_id, related_object_id))
        if related_object_id != "p1":
            return None
        return RelationshipChoice("p1", "Public project")

    projects = AdminResource(
        "projects",
        "Projects",
        "Project",
        (
            AdminField("id", "ID", required=False, read_only=True),
            AdminField("name", "Name"),
        ),
        project_repository,
        title_field="name",
    )
    tasks = AdminResource(
        "tasks",
        "Tasks",
        "Task",
        (
            AdminField("id", "ID", required=False, read_only=True),
            AdminField("name", "Name"),
            AdminField("project_id", "Project", list_display=False),
            AdminField(
                "project_name",
                "Project",
                required=False,
                read_only=True,
            ),
        ),
        task_repository,
        relationships=(
            AdminRelationship(
                "project_id",
                "projects",
                "project_name",
                search,
                resolve,
                max_choices=1,
            ),
        ),
        title_field="name",
    )
    audit_events = []

    async def authorize(context, action, admin_resource, object_id):
        return Actor("operator", "Operator")

    async def audit(event):
        audit_events.append(event)

    app = Hayate()
    site = AdminSite(
        title="Relations",
        allowed_origins={ORIGIN},
        authorize=authorize,
        audit=audit,
    )
    site.add(projects)
    site.add(tasks)
    site.register(app)

    create_form = await app.request("/admin/tasks/create")
    create_body = await response_text(create_form)
    assert create_form.status == 200
    assert "Public project" in create_body
    assert "Secret tenant project" not in create_body
    assert ">Search Project</a>" in create_body

    resolve_calls.clear()
    oversized_selection = await app.request(f"/admin/tasks/create?relation_project_id={'x' * 256}")
    assert oversized_selection.status == 403
    assert resolve_calls == []

    chooser = await app.request("/admin/tasks/relationship/project_id/choices?q=public")
    chooser_body = await response_text(chooser)
    assert chooser.status == 200
    assert "Public project" in chooser_body
    assert "Secret tenant project" not in chooser_body
    assert "relation_project_id=p1" in chooser_body

    rejected = await app.request(
        "/admin/tasks/create",
        method="POST",
        headers=mutation_headers(),
        body=urlencode({"name": "Rejected", "project_id": "secret"}),
    )
    rejected_body = await response_text(rejected)
    assert rejected.status == 422
    assert "Select an authorized related record." in rejected_body
    assert "Secret tenant project" not in rejected_body
    assert task_repository.created == []

    created = await app.request(
        "/admin/tasks/create",
        method="POST",
        headers=mutation_headers(),
        body=urlencode({"name": "Created", "project_id": "p1"}),
    )
    assert created.status == 303
    assert dict(task_repository.created[-1]) == {
        "name": "Created",
        "project_id": "p1",
    }

    search_calls.clear()
    resolve_calls.clear()
    listing = await app.request("/admin/tasks")
    assert listing.status == 200
    assert "Public project" in await response_text(listing)
    assert search_calls == []
    assert resolve_calls == []
    assert [event.phase for event in audit_events] == [
        "attempt",
        "failure",
        "attempt",
        "success",
    ]


async def test_unauthorized_preloaded_relationship_display_is_redacted():
    project_repository = SmallRepository(
        {"secret": {"id": "secret", "name": "Secret tenant project"}}
    )
    task_repository = SmallRepository(
        {
            "t1": {
                "id": "t1",
                "name": "Task",
                "project_id": "secret",
                "project_name": "Secret tenant project",
            }
        }
    )

    async def search(context, source, target, relationship, source_object_id, query):
        return RelationshipPage((), 0)

    async def resolve(
        context,
        source,
        target,
        relationship,
        source_object_id,
        related_object_id,
    ):
        return None

    projects = AdminResource(
        "projects",
        "Projects",
        "Project",
        (
            AdminField("id", "ID", required=False, read_only=True),
            AdminField("name", "Name"),
        ),
        project_repository,
    )
    tasks = AdminResource(
        "tasks",
        "Tasks",
        "Task",
        (
            AdminField("id", "ID", required=False, read_only=True),
            AdminField("name", "Name"),
            AdminField("project_id", "Project", list_display=False),
            AdminField(
                "project_name",
                "Project",
                required=False,
                read_only=True,
            ),
        ),
        task_repository,
        relationships=(
            AdminRelationship(
                "project_id",
                "projects",
                "project_name",
                search,
                resolve,
            ),
        ),
    )

    async def authorize(context, action, admin_resource, object_id):
        if admin_resource is projects and object_id == "secret":
            return None
        return Actor("operator", "Operator")

    async def audit(event):
        pass

    app = Hayate()
    site = AdminSite(
        title="Relations",
        allowed_origins={ORIGIN},
        authorize=authorize,
        audit=audit,
    )
    site.add(projects)
    site.add(tasks)
    site.register(app)
    response = await app.request("/admin/tasks")
    body = await response_text(response)
    assert response.status == 200
    assert "Secret tenant project" not in body


async def test_inline_mutations_are_single_bounded_parent_scoped_and_audited():
    repository = SmallRepository(
        {
            "parent": {
                "id": "parent",
                "name": "Parent",
                "parent_id": None,
                "parent_name": None,
            },
            "child": {
                "id": "child",
                "name": "Child",
                "parent_id": "parent",
                "parent_name": "Parent",
            },
            "other": {
                "id": "other",
                "name": "Other tenant child",
                "parent_id": "other-parent",
                "parent_name": "Other parent",
            },
        }
    )
    mutation_calls = []

    async def search(context, source, target, relationship, source_object_id, query):
        return RelationshipPage((RelationshipChoice("parent", "Parent"),), 1)

    async def resolve(
        context,
        source,
        target,
        relationship,
        source_object_id,
        related_object_id,
    ):
        record = repository.records.get(related_object_id)
        if record is None:
            return None
        return RelationshipChoice(related_object_id, str(record["name"]))

    async def read(context, parent, target, inline, parent_object_id, limit):
        children = tuple(
            record
            for record in repository.records.values()
            if record.get("parent_id") == parent_object_id
        )
        return InlineCollection(children, len(children))

    async def mutate(context, parent, target, inline, parent_object_id, mutation):
        mutation_calls.append(mutation)
        if mutation.operation == "create":
            object_id = "created-child"
            record = {
                "id": object_id,
                "name": mutation.values["name"],
                "parent_id": parent_object_id,
                "parent_name": repository.records[parent_object_id]["name"],
            }
            repository.records[object_id] = record
            return InlineMutationResult(record)
        if mutation.object_id is None:
            raise AssertionError("update/delete requires an object ID")
        record = repository.records.get(mutation.object_id)
        if record is None or record.get("parent_id") != parent_object_id:
            raise AdminValidationError({"__all__": "Inline record no longer belongs here."})
        if mutation.operation == "delete":
            del repository.records[mutation.object_id]
            return InlineMutationResult(deleted=True)
        record["name"] = mutation.values["name"]
        return InlineMutationResult(record)

    relationship = AdminRelationship(
        "parent_id",
        "trees",
        "parent_name",
        search,
        resolve,
    )
    inline = AdminInline(
        "children",
        "Children",
        "trees",
        "parent_id",
        ("name",),
        read,
        mutate,
        max_items=2,
    )
    trees = AdminResource(
        "trees",
        "Trees",
        "Tree",
        (
            AdminField("id", "ID", required=False, read_only=True),
            AdminField("name", "Name"),
            AdminField("parent_id", "Parent", required=False, list_display=False),
            AdminField(
                "parent_name",
                "Parent name",
                required=False,
                read_only=True,
                list_display=False,
            ),
        ),
        repository,
        relationships=(relationship,),
        inlines=(inline,),
        title_field="name",
    )
    audit_events = []
    denied_view_ids: set[str] = set()

    async def authorize(context, action, admin_resource, object_id):
        if action == "resource:view" and object_id in denied_view_ids:
            return None
        return Actor("operator", "Operator")

    async def audit(event):
        audit_events.append(event)

    app = Hayate()
    site = AdminSite(
        title="Inlines",
        allowed_origins={ORIGIN},
        authorize=authorize,
        audit=audit,
    )
    site.add(trees)
    site.register(app)

    detail = await app.request("/admin/trees/object/parent")
    assert ">Children</a>" in await response_text(detail)
    denied_view_ids.add("child")
    denied_editor = await app.request("/admin/trees/object/parent/inline/children")
    assert denied_editor.status == 403
    assert "Child" not in await response_text(denied_editor)
    denied_view_ids.clear()

    editor = await app.request("/admin/trees/object/parent/inline/children")
    editor_body = await response_text(editor)
    assert editor.status == 200
    assert "1 of 2 allowed records." in editor_body
    assert "Save inline record" in editor_body
    assert "Add inline record" in editor_body

    unsupported = await app.request(
        "/admin/trees/object/parent/inline/children",
        method="POST",
        headers={
            "content-type": "application/json",
            "origin": ORIGIN,
            "sec-fetch-site": "same-origin",
        },
        body="{}",
    )
    assert unsupported.status == 415

    substituted = await app.request(
        "/admin/trees/object/parent/inline/children",
        method="POST",
        headers=mutation_headers(),
        body=urlencode({"operation": "update", "object_id": "other", "name": "Stolen"}),
    )
    assert substituted.status == 422
    assert "does not belong to this parent" in await response_text(substituted)
    assert mutation_calls == []

    updated = await app.request(
        "/admin/trees/object/parent/inline/children",
        method="POST",
        headers=mutation_headers(),
        body=urlencode({"operation": "update", "object_id": "child", "name": "Updated child"}),
    )
    assert updated.status == 303
    assert repository.records["child"]["name"] == "Updated child"

    created = await app.request(
        "/admin/trees/object/parent/inline/children",
        method="POST",
        headers=mutation_headers(),
        body=urlencode({"operation": "create", "name": "Created child"}),
    )
    assert created.status == 303
    assert repository.records["created-child"]["parent_id"] == "parent"

    over_limit = await app.request(
        "/admin/trees/object/parent/inline/children",
        method="POST",
        headers=mutation_headers(),
        body=urlencode({"operation": "create", "name": "Too many"}),
    )
    assert over_limit.status == 422
    assert "At most 2 inline records are allowed." in await response_text(over_limit)
    assert len(mutation_calls) == 2

    deleted = await app.request(
        "/admin/trees/object/parent/inline/children",
        method="POST",
        headers=mutation_headers(),
        body=urlencode({"operation": "delete", "object_id": "child"}),
    )
    assert deleted.status == 303
    assert "child" not in repository.records
    assert [
        (event.phase, event.action, event.object_id, event.operation) for event in audit_events
    ] == [
        ("failure", "resource:change", None, "inline:trees:children"),
        ("failure", "resource:change", "other", "inline:trees:children"),
        ("attempt", "resource:change", "child", "inline:trees:children"),
        ("success", "resource:change", "child", "inline:trees:children"),
        ("attempt", "resource:add", None, "inline:trees:children"),
        ("success", "resource:add", "created-child", "inline:trees:children"),
        ("failure", "resource:add", None, "inline:trees:children"),
        ("attempt", "resource:delete", "child", "inline:trees:children"),
        ("success", "resource:delete", "child", "inline:trees:children"),
    ]
