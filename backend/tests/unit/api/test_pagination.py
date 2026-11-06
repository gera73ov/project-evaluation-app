"""API-003: курсорная пагинация — подпись, лимиты, следующая страница (15.1)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from estimator.api.common import ApiError, Page, PageParams, install_error_handlers
from estimator.api.common.pagination import decode_cursor, encode_cursor

pytestmark = pytest.mark.spec("15.1")

KEY = b"k" * 32
ROWS = list(range(1, 8))


def test_roundtrip() -> None:
    cursor = encode_cursor("projects", {"id": "abc"}, KEY)
    assert decode_cursor("projects", cursor, KEY) == {"id": "abc"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c[:-2],
        lambda c: c[:5] + ("A" if c[5] != "A" else "B") + c[6:],
        lambda c: "!!!",
        lambda c: "",
    ],
    ids=["truncated", "flipped", "garbage", "empty"],
)
def test_tampered_cursor_rejected(mutate) -> None:
    cursor = encode_cursor("projects", {"id": "abc"}, KEY)
    with pytest.raises(ApiError) as err:
        decode_cursor("projects", mutate(cursor), KEY)
    assert err.value.code == "CURSOR_INVALID"


def test_cursor_of_other_list_rejected() -> None:
    cursor = encode_cursor("projects", {"id": "abc"}, KEY)
    with pytest.raises(ApiError):
        decode_cursor("notifications", cursor, KEY)


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/items")
    async def items(page: PageParams) -> Page[int]:
        after = page.position("items")
        start = after["n"] if after else 0
        rows = [n for n in ROWS if n > start][: page.limit + 1]
        return Page.build(rows, page, "items", lambda n: {"n": n})

    return TestClient(app)


def test_walk_pages() -> None:
    client = _client()
    seen, cursor = [], None
    while True:
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        body = client.get("/items", params=params).json()
        seen += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == ROWS


def test_default_limit_and_last_page() -> None:
    body = _client().get("/items").json()
    assert body == {"items": ROWS, "next_cursor": None}


@pytest.mark.parametrize("limit", [0, 201, -1])
def test_limit_out_of_range(limit: int) -> None:
    r = _client().get("/items", params={"limit": limit})
    assert (r.status_code, r.json()["code"]) == (400, "CURSOR_INVALID")


def test_forged_cursor_is_400() -> None:
    r = _client().get("/items", params={"cursor": "eyJuIjo1fQ"})
    assert (r.status_code, r.json()["code"]) == (400, "CURSOR_INVALID")
