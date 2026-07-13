"""Automated input-rejection coverage for FR-002 (T013).

raster-only PDF -> raster_or_empty; corrupt/encrypted -> unreadable;
non-PDF upload -> unsupported_format. Every rejection names the offending file.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from cadmorph.api.app import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path / "data"), raise_server_exceptions=False)


def _vector_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.draw_line(fitz.Point(10, 10), fitz.Point(100, 100))
    page.insert_text(fitz.Point(20, 20), "D1 = 10 cm", fontsize=9)
    doc.save(path)
    doc.close()
    return path


def _raster_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 16, 16))
    pix.clear_with(128)
    page.insert_image(fitz.Rect(0, 0, 200, 200), stream=pix.tobytes("png"))
    doc.save(path)
    doc.close()
    return path


def _encrypted_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.draw_line(fitz.Point(10, 10), fitz.Point(50, 50))
    doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="pw", user_pw="pw")
    doc.close()
    return path


def _post(client: TestClient, old: Path, new: Path):
    with open(old, "rb") as fo, open(new, "rb") as fn:
        return client.post(
            "/api/v1/comparisons",
            files={"file_old": (old.name, fo, "application/pdf"),
                   "file_new": (new.name, fn, "application/pdf")},
        )


def _final_status(client: TestClient, comparison_id: str) -> dict:
    return client.get(f"/api/v1/comparisons/{comparison_id}").json()


def test_non_pdf_rejected_synchronously(client: TestClient, tmp_path: Path):
    dxf = tmp_path / "drawing.dxf"
    dxf.write_text("0\nSECTION\n", encoding="utf-8")
    vector = _vector_pdf(tmp_path / "ok.pdf")
    response = _post(client, dxf, vector)
    assert response.status_code == 400
    body = response.json()["error"]
    assert body["code"] == "unsupported_format"
    assert "drawing.dxf" in body["message"]


def test_raster_only_pdf_rejected(client: TestClient, tmp_path: Path):
    raster = _raster_pdf(tmp_path / "scan.pdf")
    vector = _vector_pdf(tmp_path / "ok.pdf")
    response = _post(client, raster, vector)
    assert response.status_code == 202
    status = _final_status(client, response.json()["comparison_id"])
    assert status["state"] == "rejected"
    assert status["reason"] == "raster_or_empty"
    assert "scan.pdf" in status["message"]


def test_corrupt_pdf_rejected(client: TestClient, tmp_path: Path):
    corrupt = tmp_path / "broken.pdf"
    corrupt.write_bytes(b"%PDF-1.7\n<< totally broken >>")
    vector = _vector_pdf(tmp_path / "ok.pdf")
    response = _post(client, vector, corrupt)
    assert response.status_code == 202
    status = _final_status(client, response.json()["comparison_id"])
    assert status["state"] == "rejected"
    assert status["reason"] in ("unreadable", "raster_or_empty")
    assert "broken.pdf" in status["message"]


def test_encrypted_pdf_rejected(client: TestClient, tmp_path: Path):
    encrypted = _encrypted_pdf(tmp_path / "locked.pdf")
    vector = _vector_pdf(tmp_path / "ok.pdf")
    response = _post(client, vector, encrypted)
    assert response.status_code == 202
    status = _final_status(client, response.json()["comparison_id"])
    assert status["state"] == "rejected"
    assert status["reason"] == "unreadable"
    assert "locked.pdf" in status["message"]


def test_unknown_id_404(client: TestClient):
    response = client.get("/api/v1/comparisons/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
