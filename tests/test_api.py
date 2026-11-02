import pytest
from fastapi.testclient import TestClient

from app.main import app, store

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_store():
    store.clear()
    yield
    store.clear()


def test_shorten_and_redirect():
    resp = client.post("/api/v1/links", json={"url": "https://example.com/docs"})
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["code"]) == 7
    assert body["short_url"].endswith("/" + body["code"])

    redirect = client.get("/" + body["code"], follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://example.com/docs"


def test_custom_code():
    resp = client.post("/api/v1/links", json={"url": "https://example.com", "code": "my-link"})
    assert resp.status_code == 201
    assert client.get("/api/v1/links/my-link").json()["url"] == "https://example.com/"


def test_duplicate_custom_code_conflicts():
    client.post("/api/v1/links", json={"url": "https://example.com", "code": "taken"})
    resp = client.post("/api/v1/links", json={"url": "https://example.org", "code": "taken"})
    assert resp.status_code == 409


@pytest.mark.parametrize("code", ["ab", "has space", "x" * 33, "bad/slash"])
def test_invalid_custom_code_rejected(code):
    resp = client.post("/api/v1/links", json={"url": "https://example.com", "code": code})
    assert resp.status_code == 422


@pytest.mark.parametrize("url", ["not-a-url", "ftp://example.com", ""])
def test_invalid_url_rejected(url):
    assert client.post("/api/v1/links", json={"url": url}).status_code == 422


def test_unknown_code_404():
    assert client.get("/nope123", follow_redirects=False).status_code == 404
    assert client.get("/api/v1/links/nope123").status_code == 404


def test_probes():
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").json()["status"] == "ready"


def test_metrics_use_route_templates():
    resp = client.post("/api/v1/links", json={"url": "https://example.com"})
    client.get("/" + resp.json()["code"], follow_redirects=False)
    text = client.get("/metrics").text
    assert "shortener_redirects_total" in text
    assert 'route="/{code}"' in text
    # raw codes must never become label values
    assert resp.json()["code"] not in text
