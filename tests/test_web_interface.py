"""Tests for the mobile-friendly MootOS chat interface."""

from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_chat_interface_is_served():
    response = client.get("/chat")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Talk to MootOS" in response.text
    assert "/static/app.js" in response.text
    assert "/static/styles.css" in response.text


def test_chat_interface_assets_are_served():
    script = client.get("/static/app.js")
    styles = client.get("/static/styles.css")

    assert script.status_code == 200
    assert styles.status_code == 200
    assert 'apiRequest("/chat"' in script.text
    assert "conversation_id" in script.text
    assert "@media (max-width: 860px)" in styles.text


def test_existing_chat_api_remains_available():
    route_methods = {
        method
        for route in app.routes
        if route.path == "/chat"
        for method in route.methods
    }

    assert route_methods == {"GET", "POST"}
