"""contracts/api.md: ALL non-2xx responses use the error envelope —
including framework-level 404/405, which previously leaked Starlette's
default {"detail": ...} shape and crashed envelope-expecting clients."""

from __future__ import annotations

import tempfile

import pytest
from fastapi.testclient import TestClient

from cadmorph.api.app import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(data_dir=tempfile.mkdtemp()))


def test_unknown_route_uses_envelope(client):
    response = client.post("/api/v1/comparison")  # typo'd path
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert "message" in body["error"]


def test_wrong_method_uses_envelope(client):
    response = client.get("/api/v1/comparisons")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
