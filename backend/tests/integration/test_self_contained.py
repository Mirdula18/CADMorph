"""Self-containment (FR-016, T046): a full comparison makes zero outbound
network connections; oversized uploads are rejected with the contract
envelope naming the file; no response ever grants cross-origin access."""

from __future__ import annotations

import socket
import threading

import pytest
from fastapi.testclient import TestClient

from cadmorph.api.app import create_app


@pytest.fixture()
def client(tmp_path) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path / "data"))


def test_full_comparison_with_all_network_egress_blocked(client, gt_pair, monkeypatch):
    """STRICT inventory: the only socket connects permitted at all are the
    ones socket.socketpair() makes internally — on Windows it is a
    pure-Python fallback that connects to an in-process 127.0.0.1 listener,
    and asyncio/anyio create one such pair per event loop (the TestClient
    portal's self-pipe). Every other connect — loopback included — fails.
    On platforms with native socketpair (Linux/macOS) the allowlist is
    simply never exercised and ANY connect fails."""
    unexpected: list = []
    socketpair_connects: list = []
    inside_socketpair = threading.local()

    real_socketpair = socket.socketpair
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def tracked_socketpair(*args, **kwargs):
        inside_socketpair.active = True
        try:
            return real_socketpair(*args, **kwargs)
        finally:
            inside_socketpair.active = False

    def guard(real):
        def guarded(self, address, *args, **kwargs):
            if getattr(inside_socketpair, "active", False):
                socketpair_connects.append(address)
                return real(self, address, *args, **kwargs)
            unexpected.append(address)
            raise AssertionError(f"unexpected socket connect during comparison: {address!r}")

        return guarded

    monkeypatch.setattr(socket, "socketpair", tracked_socketpair)
    monkeypatch.setattr(socket.socket, "connect", guard(real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard(real_connect_ex))

    with open(gt_pair / "v1.pdf", "rb") as f1, open(gt_pair / "v2.pdf", "rb") as f2:
        response = client.post(
            "/api/v1/comparisons",
            files={
                "file_old": ("v1.pdf", f1, "application/pdf"),
                "file_new": ("v2.pdf", f2, "application/pdf"),
            },
        )
    assert response.status_code == 202
    cid = response.json()["comparison_id"]
    status = client.get(f"/api/v1/comparisons/{cid}").json()
    assert status["state"] == "done", status  # pipeline really ran
    assert client.get(f"/api/v1/comparisons/{cid}/report").status_code == 200
    assert unexpected == []  # nothing connected outside socketpair()
    # ...and every allowlisted connect really was socketpair-internal loopback
    for address in socketpair_connects:
        assert isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"), address


def test_oversized_file_rejected_naming_the_file(client, monkeypatch):
    monkeypatch.setenv("CADMORPH_MAX_UPLOAD_MB", "1")
    big = b"%PDF-1.4" + b"\0" * (1024 * 1024 + 1)  # just over 1 MiB
    response = client.post(
        "/api/v1/comparisons",
        files={
            "file_old": ("huge.pdf", big, "application/pdf"),
            "file_new": ("ok.pdf", b"%PDF-1.4 tiny", "application/pdf"),
        },
    )
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "file_too_large"
    assert "huge.pdf" in error["message"]  # names the offender


def test_giant_request_fails_fast_on_declared_length(client, monkeypatch):
    """Content-Length beyond 2x per-file limit (+form overhead) is refused
    by the middleware before the body is buffered."""
    monkeypatch.setenv("CADMORPH_MAX_UPLOAD_MB", "1")
    big = b"\0" * (4 * 1024 * 1024)
    response = client.post(
        "/api/v1/comparisons",
        files={
            "file_old": ("a.pdf", big, "application/pdf"),
            "file_new": ("b.pdf", big, "application/pdf"),
        },
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_within_limit_upload_still_accepted(client, gt_pair):
    """Inverse of the limit: legitimate files sail through (guards against a
    limit so aggressive it breaks normal use)."""
    with open(gt_pair / "v1.pdf", "rb") as f1, open(gt_pair / "v2.pdf", "rb") as f2:
        response = client.post(
            "/api/v1/comparisons",
            files={
                "file_old": ("v1.pdf", f1, "application/pdf"),
                "file_new": ("v2.pdf", f2, "application/pdf"),
            },
        )
    assert response.status_code == 202


def test_no_cross_origin_grant_ever(client):
    """No CORS middleware is registered: a foreign Origin gets no
    Access-Control-Allow-Origin on simple requests, and preflight is not
    honored (FR-016 / contracts/api.md 'CORS locked to same origin')."""
    response = client.get(
        "/api/v1/comparisons/nonexistent", headers={"Origin": "https://evil.example"}
    )
    assert "access-control-allow-origin" not in response.headers

    preflight = client.options(
        "/api/v1/comparisons",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in preflight.headers
    assert preflight.status_code == 405  # envelope, not a grant
    assert preflight.json()["error"]["code"] == "method_not_allowed"
