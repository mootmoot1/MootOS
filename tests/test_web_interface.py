"""Tests for the mobile-friendly MootOS chat and memory interfaces."""

from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_chat_interface_is_served():
    response = client.get("/chat")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Talk to MootOS" in response.text
    assert 'action="/memory"' in response.text
    assert "/static/app.js" in response.text
    assert "/static/styles.css" in response.text
    assert "/static/memory.css" in response.text


def test_memory_review_interface_is_served():
    response = client.get("/memory")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Long-term memories" in response.text
    assert "This first version is read-only" in response.text
    assert 'id="memoryProjectFilter"' in response.text
    assert 'id="memoryList"' in response.text
    assert "/static/memory.js" in response.text
    assert "/static/memory.css" in response.text


def test_interface_assets_are_served():
    chat_script = client.get("/static/app.js")
    memory_script = client.get("/static/memory.js")
    styles = client.get("/static/styles.css")
    memory_styles = client.get("/static/memory.css")

    assert chat_script.status_code == 200
    assert memory_script.status_code == 200
    assert styles.status_code == 200
    assert memory_styles.status_code == 200
    assert 'apiRequest("/chat"' in chat_script.text
    assert "conversation_id" in chat_script.text
    assert 'apiRequest("/projects")' in memory_script.text
    assert 'let path = "/memories"' in memory_script.text
    assert "memoryRequestGeneration" in memory_script.text
    assert "requestGeneration !== memoryRequestGeneration" in memory_script.text
    assert 'method: "DELETE"' not in memory_script.text
    assert 'method: "PATCH"' not in memory_script.text
    assert 'method: "PUT"' not in memory_script.text
    assert "@media (max-width: 860px)" in styles.text
    assert "@media (max-width: 520px)" in memory_styles.text


def test_existing_chat_and_memory_api_routes_remain_available():
    chat_methods = {
        method
        for route in app.routes
        if route.path == "/chat"
        for method in route.methods
    }
    memory_page_methods = {
        method
        for route in app.routes
        if route.path == "/memory"
        for method in route.methods
    }
    memory_api_methods = {
        method
        for route in app.routes
        if route.path == "/memories"
        for method in route.methods
    }

    assert chat_methods == {"GET", "POST"}
    assert memory_page_methods == {"GET"}
    assert memory_api_methods == {"GET", "POST"}
