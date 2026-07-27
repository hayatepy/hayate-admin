from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

import pytest
from examples.sqlite import generated_queries
from examples.sqlite.app import create_example, initialize_database, seed_user
from examples.sqlite.generated_queries import create_task, list_admin_audit_events
from examples.tasks import TaskRepository

from hayate_admin import AdminValidationError

ORIGIN = "https://admin.example"
SECRET = "sqlite-example-test-secret"
PASSWORD = "correct horse battery staple"


def _cookie(response) -> str:
    return response.headers.set_cookie_list()[0].split(";", 1)[0]


async def _sign_in(app, email: str) -> str:
    response = await app.request(
        "/api/auth/sign-in/email",
        method="POST",
        headers={"origin": ORIGIN, "sec-fetch-site": "same-origin"},
        json={"email": email, "password": PASSWORD},
    )
    assert response.status == 200
    return _cookie(response)


def _mutation_headers(cookie: str) -> dict[str, str]:
    return {
        "content-type": "application/x-www-form-urlencoded",
        "cookie": cookie,
        "origin": ORIGIN,
        "sec-fetch-site": "same-origin",
    }


def _task_form(
    name: str,
    *,
    status: str = "open",
    parent_id: str | None = None,
) -> str:
    values = {
        "name": name,
        "status": status,
        "active": "true",
        "notes": "form-value-must-not-reach-audit",
    }
    if parent_id is not None:
        values["parent_id"] = parent_id
    return urlencode(values)


async def test_generated_sqlite_repository_sessions_permissions_and_redacted_audit(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "admin.db"
    initialize_database(database_path)
    viewer_id = await seed_user(
        database_path=database_path,
        origin=ORIGIN,
        auth_secret=SECRET,
        email="viewer@example.test",
        password=PASSWORD,
        role="viewer",
    )
    editor_id = await seed_user(
        database_path=database_path,
        origin=ORIGIN,
        auth_secret=SECRET,
        email="editor@example.test",
        password=PASSWORD,
        role="editor",
    )
    operator_id = await seed_user(
        database_path=database_path,
        origin=ORIGIN,
        auth_secret=SECRET,
        email="operator@example.test",
        password=PASSWORD,
        role="operator",
    )
    example = create_example(
        database_path=database_path,
        origin=ORIGIN,
        auth_secret=SECRET,
    )

    try:
        viewer = await _sign_in(example.app, "viewer@example.test")
        assert (await example.app.request("/admin/tasks", headers={"cookie": viewer})).status == 200
        denied_add = await example.app.request(
            "/admin/tasks/create",
            method="POST",
            headers=_mutation_headers(viewer),
            body=_task_form("Denied"),
        )
        assert denied_add.status == 403

        editor = await _sign_in(example.app, "editor@example.test")
        created = await example.app.request(
            "/admin/tasks/create",
            method="POST",
            headers=_mutation_headers(editor),
            body=_task_form("Audited task"),
        )
        assert created.status == 303
        assert created.headers.get("location") == "/admin/tasks/object/1"

        bulk_closed = await example.app.request(
            "/admin/tasks/bulk",
            method="POST",
            headers=_mutation_headers(editor),
            body=urlencode(
                [
                    ("action", "close"),
                    ("selected", "1"),
                ]
            ),
        )
        assert bulk_closed.status == 200
        assert "1 completed; 0 failed." in await bulk_closed.text()

        edited = await example.app.request(
            "/admin/tasks/object/1/edit",
            method="POST",
            headers=_mutation_headers(editor),
            body=_task_form("Updated task", status="closed"),
        )
        assert edited.status == 303
        history = await example.app.request(
            "/admin/tasks/object/1/history",
            headers={"cookie": editor},
        )
        history_body = await history.text()
        assert history.status == 200
        assert "resource:bulk / close" in history_body
        assert "form-value-must-not-reach-audit" not in history_body
        assert "Updated task" not in history_body
        viewer_history = await example.app.request(
            "/admin/tasks/object/1/history",
            headers={"cookie": viewer},
        )
        assert viewer_history.status == 403
        denied_delete = await example.app.request(
            "/admin/tasks/object/1/delete",
            method="POST",
            headers=_mutation_headers(editor),
            body="",
        )
        assert denied_delete.status == 403

        operator = await _sign_in(example.app, "operator@example.test")
        deleted = await example.app.request(
            "/admin/tasks/object/1/delete",
            method="POST",
            headers=_mutation_headers(operator),
            body="",
        )
        assert deleted.status == 303

        events = await list_admin_audit_events(example.database)
        assert [
            (
                event["phase"],
                event["action"],
                event["operation"],
                event["object_id"],
                event["actor_id"],
            )
            for event in events
        ] == [
            ("failure", "resource:add", None, None, None),
            ("attempt", "resource:add", None, None, editor_id),
            ("success", "resource:add", None, "1", editor_id),
            ("attempt", "resource:bulk", "close", "1", editor_id),
            ("success", "resource:bulk", "close", "1", editor_id),
            ("attempt", "resource:change", None, "1", editor_id),
            ("success", "resource:change", None, "1", editor_id),
            ("failure", "resource:delete", None, "1", None),
            ("attempt", "resource:delete", None, "1", operator_id),
            ("success", "resource:delete", None, "1", operator_id),
        ]
        assert viewer_id not in {event["actor_id"] for event in events}
        assert "form-value-must-not-reach-audit" not in repr(events)
        assert "Audited task" not in repr(events)
        assert "Updated task" not in repr(events)
    finally:
        await example.close()


async def test_sqlite_relationships_and_inlines_are_tenant_scoped_and_atomic(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "relations.db"
    initialize_database(database_path)
    await seed_user(
        database_path=database_path,
        origin=ORIGIN,
        auth_secret=SECRET,
        email="operator@example.test",
        password=PASSWORD,
        role="operator",
        tenant_key="alpha",
    )
    example = create_example(
        database_path=database_path,
        origin=ORIGIN,
        auth_secret=SECRET,
    )
    try:
        operator = await _sign_in(example.app, "operator@example.test")
        created_parent = await example.app.request(
            "/admin/tasks/create",
            method="POST",
            headers=_mutation_headers(operator),
            body=_task_form("Alpha parent"),
        )
        assert created_parent.status == 303
        assert created_parent.headers.get("location") == "/admin/tasks/object/1"

        beta = await create_task(
            example.database,
            tenant_key="beta",
            name="Beta secret",
            status="open",
            active=True,
            notes="cross-tenant-sentinel",
            parent_id=None,
        )
        assert beta["id"] == 2

        alpha_repository = TaskRepository(
            example.database,
            generated_queries,
            tenant_key="alpha",
        )
        cross_tenant_values = {
            "name": "Storage bypass",
            "status": "open",
            "active": True,
            "notes": "must not be written",
            "parent_id": "2",
        }
        with pytest.raises(AdminValidationError) as create_error:
            await alpha_repository.create(cross_tenant_values)
        assert create_error.value.errors["parent_id"] == "Select an authorized related record."
        with pytest.raises(AdminValidationError) as update_error:
            await alpha_repository.update("1", cross_tenant_values)
        assert update_error.value.errors["parent_id"] == "Select an authorized related record."
        unchanged_parent = await alpha_repository.get("1")
        assert unchanged_parent is not None
        assert unchanged_parent["parent_id"] is None

        chooser = await example.app.request(
            "/admin/tasks/relationship/parent_id/choices?q=Alpha",
            headers={"cookie": operator},
        )
        chooser_body = await chooser.text()
        assert chooser.status == 200
        assert "Alpha parent" in chooser_body
        assert "Beta secret" not in chooser_body

        cross_tenant = await example.app.request(
            "/admin/tasks/create",
            method="POST",
            headers=_mutation_headers(operator),
            body=_task_form("Rejected child", parent_id="2"),
        )
        cross_tenant_body = await cross_tenant.text()
        assert cross_tenant.status == 422
        assert "Select an authorized related record." in cross_tenant_body
        assert "Beta secret" not in cross_tenant_body
        assert (
            await example.app.request(
                "/admin/tasks/object/2",
                headers={"cookie": operator},
            )
        ).status == 404

        related = await example.app.request(
            "/admin/tasks/create",
            method="POST",
            headers=_mutation_headers(operator),
            body=_task_form("Related child", parent_id="1"),
        )
        assert related.status == 303
        assert related.headers.get("location") == "/admin/tasks/object/3"
        related_detail = await example.app.request(
            "/admin/tasks/object/3",
            headers={"cookie": operator},
        )
        related_body = await related_detail.text()
        assert related_detail.status == 200
        assert "Alpha parent" in related_body
        assert "/admin/tasks/object/1" in related_body

        inline_page = await example.app.request(
            "/admin/tasks/object/1/inline/subtasks",
            headers={"cookie": operator},
        )
        inline_body = await inline_page.text()
        assert inline_page.status == 200
        assert "Related child" in inline_body
        assert "1 of 10 allowed records." in inline_body

        inline_created = await example.app.request(
            "/admin/tasks/object/1/inline/subtasks",
            method="POST",
            headers=_mutation_headers(operator),
            body=urlencode(
                {
                    "operation": "create",
                    "name": "Inline child",
                    "status": "open",
                    "active": "true",
                    "notes": "inline-create-secret",
                }
            ),
        )
        assert inline_created.status == 303
        assert inline_created.headers.get("location") == ("/admin/tasks/object/1/inline/subtasks")

        substituted = await example.app.request(
            "/admin/tasks/object/1/inline/subtasks",
            method="POST",
            headers=_mutation_headers(operator),
            body=urlencode(
                {
                    "operation": "update",
                    "object_id": "2",
                    "name": "Stolen beta",
                    "status": "closed",
                    "active": "true",
                    "notes": "cross-parent-secret",
                }
            ),
        )
        assert substituted.status == 422
        assert "does not belong to this parent" in await substituted.text()

        inline_updated = await example.app.request(
            "/admin/tasks/object/1/inline/subtasks",
            method="POST",
            headers=_mutation_headers(operator),
            body=urlencode(
                {
                    "operation": "update",
                    "object_id": "4",
                    "name": "Updated inline child",
                    "status": "closed",
                    "active": "true",
                    "notes": "inline-update-secret",
                }
            ),
        )
        assert inline_updated.status == 303

        inline_deleted = await example.app.request(
            "/admin/tasks/object/1/inline/subtasks",
            method="POST",
            headers=_mutation_headers(operator),
            body=urlencode({"operation": "delete", "object_id": "4"}),
        )
        assert inline_deleted.status == 303

        events = await list_admin_audit_events(example.database)
        inline_events = [event for event in events if event["operation"] == "inline:tasks:subtasks"]
        assert [
            (event["phase"], event["action"], event["object_id"]) for event in inline_events
        ] == [
            ("attempt", "resource:add", None),
            ("success", "resource:add", "4"),
            ("failure", "resource:change", "2"),
            ("attempt", "resource:change", "4"),
            ("success", "resource:change", "4"),
            ("attempt", "resource:delete", "4"),
            ("success", "resource:delete", "4"),
        ]
        assert "inline-create-secret" not in repr(events)
        assert "inline-update-secret" not in repr(events)
        assert "cross-parent-secret" not in repr(events)
        assert "Beta secret" not in repr(events)
    finally:
        await example.close()
