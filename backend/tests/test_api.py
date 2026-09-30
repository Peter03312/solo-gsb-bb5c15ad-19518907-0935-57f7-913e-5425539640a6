"""HTTP-level integration tests for the FastAPI application."""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from app.main import app

from .helpers import make_xml

client = TestClient(app)


def _upload(measures=None, **kw):
    data = make_xml(
        measures or [[{"step": "C", "octave": 4}]],
        **kw,
    )
    resp = client.post(
        "/api/scores",
        files={"file": ("score.musicxml", data, "application/xml")},
    )
    return resp, data


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


def test_upload_and_list_parts():
    resp, _ = _upload()
    assert resp.status_code == 200
    body = resp.json()
    assert body["parts"][0]["name"] == "Test"
    assert body["parts"][0]["measures"] == 1
    assert "file_id" in body


def test_corrupt_upload_rejected():
    resp = client.post(
        "/api/scores",
        files={"file": ("x.musicxml", b"not xml at all", "application/xml")},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_score"


def test_transpose_endpoint_roundtrip():
    resp, _ = _upload([
        [{"step": "C", "octave": 4}, {"step": "E", "octave": 4, "chord": True}],
        [{"rest": True}],
    ])
    file_id = resp.json()["file_id"]
    tr = client.post("/api/transpose", json={
        "file_id": file_id,
        "part_id": "P1",
        "src_letters": 0,
        "src_semitones": 0,
        "dst_letters": -1,
        "dst_semitones": -2,
        "range_low": "C3",
        "range_high": "C6",
        "output_label": "小号",
    })
    assert tr.status_code == 200, tr.text
    body = tr.json()
    assert body["measures"] == 2
    assert body["notes"] == 2
    # preview parses as XML and contains the transpose hint
    out = etree.fromstring(body["preview_xml"].encode())
    assert out.find(".//transpose/chromatic").text == "2"
    # download works
    dl = client.get(body["download_url"])
    assert dl.status_code == 200
    etree.fromstring(dl.content)


def test_transpose_unpitched_rejected_entirely():
    resp, _ = _upload([[{"unpitched": True}]])
    file_id = resp.json()["file_id"]
    tr = client.post("/api/transpose", json={
        "file_id": file_id,
        "part_id": "P1",
        "src_letters": 0, "src_semitones": 0,
        "dst_letters": -1, "dst_semitones": -2,
        "range_low": "C3", "range_high": "C6",
    })
    assert tr.status_code == 422
    assert tr.json()["detail"]["code"] == "unpitched"


def test_out_of_range_returns_structured_violations():
    resp, _ = _upload([[{"step": "C", "octave": 4}]])
    file_id = resp.json()["file_id"]
    tr = client.post("/api/transpose", json={
        "file_id": file_id,
        "part_id": "P1",
        "src_letters": 0, "src_semitones": 0,
        "dst_letters": -1, "dst_semitones": -2,
        "range_low": "G4", "range_high": "C6",
    })
    assert tr.status_code == 422
    detail = tr.json()["detail"]
    assert detail["code"] == "out_of_range"
    assert detail["violations"][0]["measure"] == "1"
    assert detail["violations"][0]["pitch"] == "D4"


def test_invalid_interval_rejected():
    resp, _ = _upload()
    file_id = resp.json()["file_id"]
    tr = client.post("/api/transpose", json={
        "file_id": file_id,
        "part_id": "P1",
        "src_letters": 0, "src_semitones": 0,
        "dst_letters": 1, "dst_semitones": 6,  # impossible interval
        "range_low": "C3", "range_high": "C6",
    })
    assert tr.status_code == 422
    assert tr.json()["detail"]["code"] == "invalid_params"


def test_mxl_compressed_container_supported():
    xml = make_xml([[{"step": "C", "octave": 4}]])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "META-INF/container.xml",
            """<container><rootfiles>
            <rootfile full-path="score/score.musicxml"/>
            </rootfiles></container>""",
        )
        zf.writestr("score/score.musicxml", xml)
    resp = client.post(
        "/api/scores",
        files={"file": ("score.mxl", buf.getvalue(), "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["parts"][0]["measures"] == 1
