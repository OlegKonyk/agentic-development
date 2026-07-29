from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def future_iso(minutes: int = 5) -> str:
    return iso(datetime.now(UTC) + timedelta(minutes=minutes))


async def create(client: AsyncClient, headers: dict[str, str], **overrides: object) -> dict:
    payload: dict[str, object] = {"title": "A task", **overrides}
    resp = await client.post("/api/tasks", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_healthz(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_openapi_available(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert "/api/tasks" in resp.json()["paths"]


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/api/tasks"),
        ("POST", "/api/tasks"),
        ("GET", "/api/tasks/1"),
        ("PATCH", "/api/tasks/1"),
        ("DELETE", "/api/tasks/1"),
    ],
)
async def test_endpoints_require_auth(client: AsyncClient, method: str, url: str) -> None:
    resp = await client.request(method, url, json={"title": "x"})
    assert resp.status_code == 401


async def test_create_task_defaults(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    task = await create(client, alice_headers, title="Buy milk")
    assert task["title"] == "Buy milk"
    assert task["description"] == ""
    assert task["status"] == "todo"
    assert task["due_at"] is None
    assert task["reminder_status"] == "none"
    assert isinstance(task["id"], int)
    assert task["created_at"].endswith("Z")
    datetime.fromisoformat(task["created_at"])  # valid RFC 3339


async def test_create_with_future_due_at(client: AsyncClient, alice_headers: dict) -> None:
    due = future_iso()
    task = await create(client, alice_headers, title="Remind me", due_at=due)
    assert task["due_at"] == due
    assert task["reminder_status"] == "none"


@pytest.mark.parametrize("due_at", ["2020-01-01T00:00:00Z", "not-a-date"])
async def test_create_bad_due_at_422(client: AsyncClient, alice_headers: dict, due_at: str) -> None:
    resp = await client.post(
        "/api/tasks", json={"title": "x", "due_at": due_at}, headers=alice_headers
    )
    assert resp.status_code == 422


async def test_reminder_status_is_read_only(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, reminder_status="sent")
    assert task["reminder_status"] == "none"


async def test_create_title_boundaries(client: AsyncClient, alice_headers: dict) -> None:
    ok = await client.post("/api/tasks", json={"title": "x" * 200}, headers=alice_headers)
    assert ok.status_code == 201
    too_long = await client.post("/api/tasks", json={"title": "x" * 201}, headers=alice_headers)
    assert too_long.status_code == 422
    empty = await client.post("/api/tasks", json={"title": ""}, headers=alice_headers)
    assert empty.status_code == 422
    blank = await client.post("/api/tasks", json={"title": " "}, headers=alice_headers)
    assert blank.status_code == 422
    missing = await client.post("/api/tasks", json={"description": "x"}, headers=alice_headers)
    assert missing.status_code == 422


@pytest.mark.parametrize("title", [" ", "\t", "\n", "   ", " "])
async def test_create_whitespace_only_title_422(
    client: AsyncClient, alice_headers: dict, title: str
) -> None:
    resp = await client.post("/api/tasks", json={"title": title}, headers=alice_headers)
    assert resp.status_code == 422
    listed = await client.get("/api/tasks", headers=alice_headers)
    assert listed.json()["items"] == []


async def test_blank_title_422_names_title_field(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.post("/api/tasks", json={"title": " "}, headers=alice_headers)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail[0]["loc"] == ["body", "title"]
    assert detail[0]["type"] == "value_error"


async def test_create_padded_title_stored_verbatim(
    client: AsyncClient, alice_headers: dict
) -> None:
    task = await create(client, alice_headers, title="  Buy milk  ")
    assert task["title"] == "  Buy milk  "


async def test_patch_whitespace_only_title_422(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="keep me", description="keep too")
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"title": " "}, headers=alice_headers
    )
    assert resp.status_code == 422
    fetched = await client.get(f"/api/tasks/{task['id']}", headers=alice_headers)
    assert fetched.json()["title"] == "keep me"
    assert fetched.json()["description"] == "keep too"
    assert fetched.json()["status"] == "todo"


async def test_patch_null_title_is_noop(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="unchanged")
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"title": None}, headers=alice_headers
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "unchanged"


async def test_list_tasks_and_status_filter(client: AsyncClient, alice_headers: dict) -> None:
    a = await create(client, alice_headers, title="one")
    b = await create(client, alice_headers, title="two")
    await client.patch(f"/api/tasks/{b['id']}", json={"status": "doing"}, headers=alice_headers)

    all_resp = await client.get("/api/tasks", headers=alice_headers)
    assert all_resp.status_code == 200
    assert [t["id"] for t in all_resp.json()["items"]] == [a["id"], b["id"]]

    todo = await client.get("/api/tasks", params={"status": "todo"}, headers=alice_headers)
    assert [t["id"] for t in todo.json()["items"]] == [a["id"]]

    done = await client.get("/api/tasks", params={"status": "done"}, headers=alice_headers)
    assert done.json()["items"] == []


async def test_list_tasks_invalid_status_filter(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.get("/api/tasks", params={"status": "bogus"}, headers=alice_headers)
    assert resp.status_code == 422


async def test_owner_scoping(client: AsyncClient, alice_headers: dict, bob_headers: dict) -> None:
    alice_task = await create(client, alice_headers, title="alice's")
    bob_task = await create(client, bob_headers, title="bob's")

    alice_list = (await client.get("/api/tasks", headers=alice_headers)).json()["items"]
    assert [t["id"] for t in alice_list] == [alice_task["id"]]
    bob_list = (await client.get("/api/tasks", headers=bob_headers)).json()["items"]
    assert [t["id"] for t in bob_list] == [bob_task["id"]]


async def test_cross_user_task_ids_404(
    client: AsyncClient, alice_headers: dict, bob_headers: dict
) -> None:
    task = await create(client, alice_headers, title="private")
    url = f"/api/tasks/{task['id']}"
    assert (await client.get(url, headers=bob_headers)).status_code == 404
    patch = await client.patch(url, json={"status": "done"}, headers=bob_headers)
    assert patch.status_code == 404
    assert (await client.delete(url, headers=bob_headers)).status_code == 404
    # Untouched for the owner.
    assert (await client.get(url, headers=alice_headers)).status_code == 200


async def test_get_task(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="find me")
    resp = await client.get(f"/api/tasks/{task['id']}", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json() == task


async def test_get_unknown_task_404(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.get("/api/tasks/9999", headers=alice_headers)
    assert resp.status_code == 404


async def test_task_id_out_of_range_422(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.get(f"/api/tasks/{2**63}", headers=alice_headers)
    assert resp.status_code == 422


async def test_patch_fields(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="old", description="d")
    due = future_iso()
    resp = await client.patch(
        f"/api/tasks/{task['id']}",
        json={"title": "new", "description": "e", "status": "done", "due_at": due},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "new"
    assert body["description"] == "e"
    assert body["status"] == "done"
    assert body["due_at"] == due


async def test_patch_partial_leaves_other_fields(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="keep me", description="keep too")
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"status": "doing"}, headers=alice_headers
    )
    body = resp.json()
    assert body["title"] == "keep me"
    assert body["description"] == "keep too"
    assert body["status"] == "doing"


async def test_patch_empty_body_is_noop(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="unchanged")
    resp = await client.patch(f"/api/tasks/{task['id']}", json={}, headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json() == task


async def test_patch_past_due_at_422(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers)
    resp = await client.patch(
        f"/api/tasks/{task['id']}",
        json={"due_at": "2020-01-01T00:00:00Z"},
        headers=alice_headers,
    )
    assert resp.status_code == 422


async def test_patch_explicit_null_due_at_clears_it(
    client: AsyncClient, alice_headers: dict
) -> None:
    task = await create(client, alice_headers, due_at=future_iso())
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"due_at": None}, headers=alice_headers
    )
    assert resp.status_code == 200
    assert resp.json()["due_at"] is None
    fetched = await client.get(f"/api/tasks/{task['id']}", headers=alice_headers)
    assert fetched.json()["due_at"] is None


async def test_patch_omitting_due_at_keeps_it(client: AsyncClient, alice_headers: dict) -> None:
    due = future_iso()
    task = await create(client, alice_headers, due_at=due)
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"title": "renamed"}, headers=alice_headers
    )
    assert resp.status_code == 200
    assert resp.json()["due_at"] == due


async def test_patch_null_due_at_leaves_other_fields_and_reminder_status(
    client: AsyncClient, alice_headers: dict
) -> None:
    task = await create(
        client, alice_headers, title="keep title", description="keep desc", due_at=future_iso()
    )
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"due_at": None}, headers=alice_headers
    )
    body = resp.json()
    assert body["title"] == "keep title"
    assert body["description"] == "keep desc"
    assert body["status"] == "todo"
    assert body["reminder_status"] == "none"


async def test_patch_title_only_does_not_revalidate_past_due_at(
    client: AsyncClient, alice_headers: dict
) -> None:
    from app import db
    from app.models import Task

    async with db.session_scope() as session:
        task = Task(
            owner_id=1,
            title="past due",
            due_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = task.id

    resp = await client.patch(
        f"/api/tasks/{task_id}", json={"title": "still past due"}, headers=alice_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "still past due"
    assert body["due_at"] == "2020-01-01T00:00:00Z"


async def test_patch_null_due_at_other_users_task_is_404(
    client: AsyncClient, alice_headers: dict, bob_headers: dict
) -> None:
    task = await create(client, alice_headers, due_at=future_iso())
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"due_at": None}, headers=bob_headers
    )
    assert resp.status_code == 404
    fetched = await client.get(f"/api/tasks/{task['id']}", headers=alice_headers)
    assert fetched.json()["due_at"] is not None


async def test_patch_invalid_status_422(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers)
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"status": "finished"}, headers=alice_headers
    )
    assert resp.status_code == 422


async def test_patch_unknown_task_404(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.patch("/api/tasks/9999", json={"status": "done"}, headers=alice_headers)
    assert resp.status_code == 404


async def test_delete_task(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="doomed")
    resp = await client.delete(f"/api/tasks/{task['id']}", headers=alice_headers)
    assert resp.status_code == 204
    assert resp.content == b""
    assert (await client.get(f"/api/tasks/{task['id']}", headers=alice_headers)).status_code == 404


async def test_delete_unknown_task_404(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.delete("/api/tasks/9999", headers=alice_headers)
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        '{"title": "\\ud800"}',
        '{"title": "ok", "description": "a\\u0000b"}',
    ],
    ids=["surrogate-title", "nul-description"],
)
async def test_create_task_unstorable_strings_422(
    client: AsyncClient, alice_headers: dict, body: str
) -> None:
    # Same family as the login regression: surrogates/NUL crash the asyncpg
    # bind into a 500 unless rejected at the model boundary.
    resp = await client.post(
        "/api/tasks",
        content=body.encode("utf-8"),
        headers={"Content-Type": "application/json", **alice_headers},
    )
    assert resp.status_code == 422


async def test_patch_surrogate_status_echo_is_422_not_500(
    client: AsyncClient, alice_headers: dict
) -> None:
    # Body validation fires before the 404 lookup, so no task row is needed.
    # Pins the echo path alone: status is a Literal (no storable-string
    # validator), so the 422 body reflects the raw surrogate input, which
    # used to crash response serialization into a 500.
    resp = await client.patch(
        "/api/tasks/1",
        content=b'{"status": "\\ud800"}',
        headers={"Content-Type": "application/json", **alice_headers},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]


# --- pagination (issue #8) --------------------------------------------------


async def test_list_returns_envelope_shape(client: AsyncClient, alice_headers: dict) -> None:
    await create(client, alice_headers, title="only task")
    resp = await client.get("/api/tasks", headers=alice_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "total", "limit", "offset"}
    assert body["limit"] == 20
    assert body["offset"] == 0


async def test_list_default_limit_caps_page(client: AsyncClient, alice_headers: dict) -> None:
    for i in range(25):
        await create(client, alice_headers, title=f"task {i}")
    resp = await client.get("/api/tasks", headers=alice_headers)
    body = resp.json()
    assert len(body["items"]) == 20
    assert body["total"] == 25


async def test_list_limit_offset_slice(client: AsyncClient, alice_headers: dict) -> None:
    tasks = [await create(client, alice_headers, title=f"task {i}") for i in range(12)]
    resp = await client.get("/api/tasks", params={"limit": 5, "offset": 5}, headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [t["id"] for t in tasks[5:10]]
    assert body["limit"] == 5
    assert body["offset"] == 5


async def test_list_total_stable_across_pages(client: AsyncClient, alice_headers: dict) -> None:
    for i in range(12):
        await create(client, alice_headers, title=f"task {i}")
    first = await client.get("/api/tasks", params={"limit": 5, "offset": 0}, headers=alice_headers)
    second = await client.get("/api/tasks", params={"limit": 5, "offset": 5}, headers=alice_headers)
    assert first.json()["total"] == second.json()["total"] == 12


async def test_list_offset_past_end_is_empty_200(client: AsyncClient, alice_headers: dict) -> None:
    for i in range(3):
        await create(client, alice_headers, title=f"task {i}")
    resp = await client.get("/api/tasks", params={"offset": 100}, headers=alice_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 3


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": -1},
        {"offset": -1},
        {"limit": "abc"},
        {"offset": 1.5},
    ],
)
async def test_list_invalid_pagination_params_422(
    client: AsyncClient, alice_headers: dict, params: dict
) -> None:
    resp = await client.get("/api/tasks", params=params, headers=alice_headers)
    assert resp.status_code == 422


async def test_list_huge_offset_422_not_500(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.get("/api/tasks", params={"offset": 2**63}, headers=alice_headers)
    assert resp.status_code == 422


async def test_list_status_filter_scopes_page_and_total(
    client: AsyncClient, alice_headers: dict
) -> None:
    for i in range(8):
        await create(client, alice_headers, title=f"todo {i}")
    for i in range(2):
        done = await create(client, alice_headers, title=f"done {i}")
        await client.patch(
            f"/api/tasks/{done['id']}", json={"status": "done"}, headers=alice_headers
        )

    resp = await client.get(
        "/api/tasks", params={"status": "todo", "limit": 5}, headers=alice_headers
    )
    body = resp.json()
    assert len(body["items"]) == 5
    assert all(t["status"] == "todo" for t in body["items"])
    assert body["total"] == 8


async def test_list_pagination_is_owner_scoped(
    client: AsyncClient, alice_headers: dict, bob_headers: dict
) -> None:
    alice_tasks = [await create(client, alice_headers, title=f"alice {i}") for i in range(3)]
    await create(client, bob_headers, title="bob's")

    resp = await client.get("/api/tasks", params={"limit": 100, "offset": 0}, headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [t["id"] for t in alice_tasks]
    assert body["total"] == 3


# --- urgency ordering (issue #52) -------------------------------------------


async def test_list_orders_by_due_at_then_undated(client: AsyncClient, alice_headers: dict) -> None:
    # Created out of urgency order, so a passing test can't be an id-order accident.
    soon = await create(client, alice_headers, title="soon", due_at=future_iso(30))
    later = await create(client, alice_headers, title="later", due_at=future_iso(60))
    undated = await create(client, alice_headers, title="undated")
    sooner = await create(client, alice_headers, title="sooner", due_at=future_iso(5))

    resp = await client.get("/api/tasks", headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [
        sooner["id"],
        soon["id"],
        later["id"],
        undated["id"],
    ]


async def test_list_ties_break_by_ascending_id(client: AsyncClient, alice_headers: dict) -> None:
    shared_due = future_iso(30)
    tied_a = await create(client, alice_headers, title="tied a", due_at=shared_due)
    tied_b = await create(client, alice_headers, title="tied b", due_at=shared_due)
    tied_c = await create(client, alice_headers, title="tied c", due_at=shared_due)
    undated_a = await create(client, alice_headers, title="undated a")
    undated_b = await create(client, alice_headers, title="undated b")

    resp = await client.get("/api/tasks", headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [
        tied_a["id"],
        tied_b["id"],
        tied_c["id"],
        undated_a["id"],
        undated_b["id"],
    ]


async def test_list_urgency_order_survives_paging(client: AsyncClient, alice_headers: dict) -> None:
    # Interleave due dates and undated tasks so id order and urgency order disagree.
    specs = [future_iso(60 - i) if i % 2 == 0 else None for i in range(12)]
    created = [
        await create(client, alice_headers, title=f"task {i}", **({"due_at": d} if d else {}))
        for i, d in enumerate(specs)
    ]
    full = await client.get("/api/tasks", params={"limit": 100}, headers=alice_headers)
    expected = [t["id"] for t in full.json()["items"]]
    assert len(expected) == len(created)

    paged: list[int] = []
    for offset in range(0, 12, 5):
        page = await client.get(
            "/api/tasks", params={"limit": 5, "offset": offset}, headers=alice_headers
        )
        paged.extend(t["id"] for t in page.json()["items"])
    assert paged == expected


async def test_list_pages_cover_every_task_once(client: AsyncClient, alice_headers: dict) -> None:
    for i in range(15):
        due = future_iso(30 + i) if i % 3 == 0 else None
        await create(client, alice_headers, title=f"task {i}", **({"due_at": due} if due else {}))

    seen: list[int] = []
    offset = 0
    while True:
        page = await client.get(
            "/api/tasks", params={"limit": 4, "offset": offset}, headers=alice_headers
        )
        items = page.json()["items"]
        if not items:
            break
        seen.extend(t["id"] for t in items)
        offset += 4
    assert len(seen) == len(set(seen)) == 15


async def test_list_limit_one_returns_most_urgent(client: AsyncClient, alice_headers: dict) -> None:
    await create(client, alice_headers, title="undated")
    await create(client, alice_headers, title="far", due_at=future_iso(120))
    soonest = await create(client, alice_headers, title="soonest", due_at=future_iso(5))

    resp = await client.get("/api/tasks", params={"limit": 1, "offset": 0}, headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [soonest["id"]]


async def test_list_limit_one_returns_undated_only_when_no_dated_tasks(
    client: AsyncClient, alice_headers: dict
) -> None:
    first = await create(client, alice_headers, title="first")
    await create(client, alice_headers, title="second")

    resp = await client.get("/api/tasks", params={"limit": 1, "offset": 0}, headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [first["id"]]


async def test_list_status_filter_is_urgency_ordered(
    client: AsyncClient, alice_headers: dict
) -> None:
    todo_soon = await create(client, alice_headers, title="todo soon", due_at=future_iso(10))
    todo_far = await create(client, alice_headers, title="todo far", due_at=future_iso(50))
    done = await create(client, alice_headers, title="done", due_at=future_iso(5))
    await client.patch(f"/api/tasks/{done['id']}", json={"status": "done"}, headers=alice_headers)

    resp = await client.get("/api/tasks", params={"status": "todo"}, headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [todo_soon["id"], todo_far["id"]]
    assert body["total"] == 2


async def test_list_urgency_order_is_owner_scoped(
    client: AsyncClient, alice_headers: dict, bob_headers: dict
) -> None:
    alice_task = await create(client, alice_headers, title="alice's", due_at=future_iso(60))
    await create(client, bob_headers, title="bob's sooner", due_at=future_iso(5))

    resp = await client.get("/api/tasks", params={"limit": 1, "offset": 0}, headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [alice_task["id"]]


# --- title search (issue #55) ------------------------------------------------


async def test_list_search_matches_title_substring_case_insensitively(
    client: AsyncClient, alice_headers: dict
) -> None:
    invoice = await create(client, alice_headers, title="Send invoice")
    await create(client, alice_headers, title="Buy milk")

    lower = await client.get("/api/tasks", params={"q": "inv"}, headers=alice_headers)
    assert [t["id"] for t in lower.json()["items"]] == [invoice["id"]]

    upper = await client.get("/api/tasks", params={"q": "INVOICE"}, headers=alice_headers)
    assert [t["id"] for t in upper.json()["items"]] == [invoice["id"]]


async def test_list_search_excludes_non_matching_tasks(
    client: AsyncClient, alice_headers: dict
) -> None:
    await create(client, alice_headers, title="Send invoice")
    milk = await create(client, alice_headers, title="Buy milk")

    resp = await client.get("/api/tasks", params={"q": "milk"}, headers=alice_headers)
    assert [t["id"] for t in resp.json()["items"]] == [milk["id"]]


async def test_list_search_ignores_description_and_status(
    client: AsyncClient, alice_headers: dict
) -> None:
    task = await create(client, alice_headers, title="unrelated", description="invoice details")
    await client.patch(f"/api/tasks/{task['id']}", json={"status": "doing"}, headers=alice_headers)

    resp = await client.get("/api/tasks", params={"q": "invoice"}, headers=alice_headers)
    assert resp.json()["items"] == []


async def test_list_search_composes_with_status_filter(
    client: AsyncClient, alice_headers: dict
) -> None:
    todo_invoice = await create(client, alice_headers, title="Send invoice")
    done_invoice = await create(client, alice_headers, title="Send invoice too")
    await client.patch(
        f"/api/tasks/{done_invoice['id']}", json={"status": "done"}, headers=alice_headers
    )
    await create(client, alice_headers, title="Buy milk")

    resp = await client.get(
        "/api/tasks", params={"q": "invoice", "status": "todo"}, headers=alice_headers
    )
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [todo_invoice["id"]]
    assert body["total"] == 1


async def test_list_search_total_describes_matched_set_and_is_stable_across_pages(
    client: AsyncClient, alice_headers: dict
) -> None:
    for i in range(8):
        await create(client, alice_headers, title=f"invoice {i}")
    await create(client, alice_headers, title="unrelated")

    first = await client.get(
        "/api/tasks", params={"q": "invoice", "limit": 5, "offset": 0}, headers=alice_headers
    )
    second = await client.get(
        "/api/tasks", params={"q": "invoice", "limit": 5, "offset": 5}, headers=alice_headers
    )
    assert first.json()["total"] == second.json()["total"] == 8
    assert len(first.json()["items"]) == 5
    assert len(second.json()["items"]) == 3


async def test_list_search_preserves_urgency_order(
    client: AsyncClient, alice_headers: dict
) -> None:
    later = await create(client, alice_headers, title="invoice later", due_at=future_iso(60))
    undated = await create(client, alice_headers, title="invoice undated")
    sooner = await create(client, alice_headers, title="invoice sooner", due_at=future_iso(5))

    resp = await client.get("/api/tasks", params={"q": "invoice"}, headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [sooner["id"], later["id"], undated["id"]]


async def test_list_search_pages_cover_every_match_once(
    client: AsyncClient, alice_headers: dict
) -> None:
    created = [await create(client, alice_headers, title=f"invoice {i}") for i in range(10)]
    await create(client, alice_headers, title="something else")

    seen: list[int] = []
    offset = 0
    while True:
        page = await client.get(
            "/api/tasks",
            params={"q": "invoice", "limit": 4, "offset": offset},
            headers=alice_headers,
        )
        items = page.json()["items"]
        if not items:
            break
        seen.extend(t["id"] for t in items)
        offset += 4
    assert sorted(seen) == sorted(t["id"] for t in created)


async def test_list_search_is_owner_scoped(
    client: AsyncClient, alice_headers: dict, bob_headers: dict
) -> None:
    alice_task = await create(client, alice_headers, title="Shared title")
    await create(client, bob_headers, title="Shared title")

    resp = await client.get("/api/tasks", params={"q": "Shared"}, headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [alice_task["id"]]
    assert body["total"] == 1


async def test_list_search_offset_past_end_is_empty_200_with_matched_total(
    client: AsyncClient, alice_headers: dict
) -> None:
    for i in range(3):
        await create(client, alice_headers, title=f"invoice {i}")

    resp = await client.get(
        "/api/tasks", params={"q": "invoice", "offset": 100}, headers=alice_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 3


async def test_list_search_percent_matches_literally(
    client: AsyncClient, alice_headers: dict
) -> None:
    percent_task = await create(client, alice_headers, title="100% done")
    await create(client, alice_headers, title="other task")

    matched = await client.get("/api/tasks", params={"q": "100%"}, headers=alice_headers)
    assert [t["id"] for t in matched.json()["items"]] == [percent_task["id"]]

    wildcard = await client.get("/api/tasks", params={"q": "%"}, headers=alice_headers)
    assert [t["id"] for t in wildcard.json()["items"]] == [percent_task["id"]]


async def test_list_search_underscore_and_backslash_match_literally(
    client: AsyncClient, alice_headers: dict
) -> None:
    task = await create(client, alice_headers, title="a_b")
    await create(client, alice_headers, title="axb")

    underscore = await client.get("/api/tasks", params={"q": "a_b"}, headers=alice_headers)
    assert [t["id"] for t in underscore.json()["items"]] == [task["id"]]

    no_match = await client.get("/api/tasks", params={"q": "axb_"}, headers=alice_headers)
    assert no_match.json()["items"] == []


@pytest.mark.parametrize("term", ["", "   "])
async def test_list_search_blank_and_whitespace_only_returns_full_list(
    client: AsyncClient, alice_headers: dict, term: str
) -> None:
    a = await create(client, alice_headers, title="one")
    b = await create(client, alice_headers, title="two")

    resp = await client.get("/api/tasks", params={"q": term}, headers=alice_headers)
    assert resp.status_code == 200
    assert {t["id"] for t in resp.json()["items"]} == {a["id"], b["id"]}


async def test_list_search_absent_is_unchanged(client: AsyncClient, alice_headers: dict) -> None:
    a = await create(client, alice_headers, title="one")
    b = await create(client, alice_headers, title="two")

    with_q = await client.get("/api/tasks", headers=alice_headers)
    assert {t["id"] for t in with_q.json()["items"]} == {a["id"], b["id"]}


async def test_list_search_over_max_length_422(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.get("/api/tasks", params={"q": "x" * 1001}, headers=alice_headers)
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)


async def test_list_search_nul_is_422_not_500(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.get("/api/tasks", params={"q": "bad\x00term"}, headers=alice_headers)
    assert resp.status_code == 422


async def test_list_search_unicode_and_emoji_term_matches(
    client: AsyncClient, alice_headers: dict
) -> None:
    task = await create(client, alice_headers, title="Cafe ☕ \U0001f600 opening")

    resp = await client.get("/api/tasks", params={"q": "☕"}, headers=alice_headers)
    assert [t["id"] for t in resp.json()["items"]] == [task["id"]]
