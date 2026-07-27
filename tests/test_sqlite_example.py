from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from examples.sqlite.app import create_example, initialize_database, seed_user
from examples.sqlite.generated_queries import list_admin_audit_events

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


def _task_form(name: str, *, status: str = "open") -> str:
    return urlencode(
        {
            "name": name,
            "status": status,
            "active": "true",
            "notes": "form-value-must-not-reach-audit",
        }
    )


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
