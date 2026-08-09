"""Proves every MootOS page links to every other page (self excluded).

Plain HTML/JS pages duplicate their own markup (no shared template), so
"consistent navigation" here means each page's rendered HTML contains a
link to every other page's path. This test enumerates that expectation in
one table instead of relying on eyeballing six separate files.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.application import app
from backend.db import DATABASE_PATH
from backend.memory import init_db


PAGES = ("/chat", "/memory", "/task", "/activity", "/settings", "/profile")


@pytest.fixture
def clean_db(monkeypatch):
    monkeypatch.delenv("MOOTOS_PASSWORD", raising=False)
    monkeypatch.delenv("MOOTOS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    paths = [
        Path(DATABASE_PATH),
        Path(f"{DATABASE_PATH}-wal"),
        Path(f"{DATABASE_PATH}-shm"),
    ]
    for path in paths:
        if path.exists():
            path.unlink()
    init_db()
    yield
    for path in paths:
        if path.exists():
            path.unlink()


@pytest.fixture
def client():
    return TestClient(app)


HREF_BASED_PAGES = tuple(page for page in PAGES if page != "/chat")


@pytest.mark.parametrize("page", HREF_BASED_PAGES)
def test_every_href_based_page_links_to_every_other_page(clean_db, client, page):
    """/memory, /task, /activity, /settings, /profile all use <a href>."""
    response = client.get(page)
    assert response.status_code == 200

    for other_page in PAGES:
        if other_page == page:
            continue
        assert f'href="{other_page}"' in response.text, (
            f"{page} is missing a link to {other_page}"
        )


def test_chat_page_reaches_every_other_page_through_its_sidebar_nav_forms(clean_db, client):
    """Chat uses <form action="..."> sidebar buttons, not <a href>, so it
    needs its own assertion shape rather than the href check above."""
    response = client.get("/chat")

    for other_page in PAGES:
        if other_page == "/chat":
            continue
        assert f'action="{other_page}"' in response.text, (
            f"/chat is missing a nav form to {other_page}"
        )
