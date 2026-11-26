"""Exercise the real web writer and reader with headless synthetic point clouds."""

import hashlib
import json
import time
from threading import Event

import numpy as np
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("lidar_cropper")
import laspy
from plyfile import PlyData, PlyElement

from app.core.config import settings
from app.modules.lidar_crop import PREVIEW_DTYPE
from app.services import lidar as lidar_service
from main import create_app


API = "/api/v1/lidar"
POINTS = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 0, 1], [0, 0, 2], [2, 0, 0], [0, 1, 1]])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "jobs_dir", str(tmp_path / "jobs"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    with TestClient(create_app()) as session:
        yield session
    assert not list((tmp_path / "lidar").iterdir())


def make_las(filename, points=POINTS):
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = np.full(3, .001)
    header.offsets = np.array([100., 200., -300.])
    data = laspy.LasData(header)
    data.x, data.y, data.z = points.T
    data.intensity = np.arange(len(points), dtype=np.uint16)
    data.gps_time = np.arange(len(points), dtype=np.float64) + .1875
    data.classification = np.full(len(points), 2, dtype=np.uint8)
    data.return_number = np.ones(len(points), dtype=np.uint8)
    data.number_of_returns = np.ones(len(points), dtype=np.uint8)
    data.red = np.full(len(points), 42_000, dtype=np.uint16)
    data.write(filename)
    return data


def upload(client, filename, content=None, *, declared_size=None):
    content = filename.read_bytes() if content is None else content
    size = len(content) if declared_size is None else declared_size
    return client.post(f"{API}/sources", content=content, headers={
        "Content-Type": "application/octet-stream",
        "X-Lidar-Filename": filename.name,
        "X-Lidar-Size": str(size),
    })


def status(client, url, auth):
    end = time.monotonic() + 10
    while time.monotonic() < end:
        response = client.get(url, headers=auth)
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] not in {"queued", "running"}:
            return body
        time.sleep(.025)
    pytest.fail("LiDAR worker did not finish")


def open_source(client, path):
    response = upload(client, path)
    assert response.status_code == 202, response.text
    result = response.json()
    url = f"{API}/sources/{result['id']}"
    headers = {"Authorization": f"Bearer {result['token']}"}
    inspected = status(client, url, headers)
    assert inspected["status"] == "completed", inspected
    return url, headers, inspected


def crop_payload(source, output, shape="sphere", **kwargs):
    return {"source_sha256": source["sha256"], "output_format": output,
            "selection": {"shape": shape, "center": [0, 0, 0], "radius": 1, **kwargs}}


def start_job(client, url, auth, selection):
    response = client.post(url + "/jobs", json=selection, headers=auth)
    assert response.status_code == 202, response.text
    return url + "/jobs/" + response.json()["id"]


def download(client, url, auth, kind):
    ticket_response = client.post(url + f"/download/{kind}", headers=auth)
    assert ticket_response.status_code == 200, ticket_response.text
    result = client.get(f"{API}/downloads/{ticket_response.json()['ticket']}")
    assert result.status_code == 200 and "attachment" in result.headers["content-disposition"], result.text
    return result.content


@pytest.mark.parametrize(("incoming", "outgoing", "shape", "extra", "selected"), [
    ("las", "laz", "sphere", {}, [0, 1, 3]),
    ("laz", "las", "cylinder", {"axis": "z", "height": 4}, [0, 1, 3, 4, 6]),
    ("las", "las", "cylinder", {"axis": "x", "height": 4, "radius": .25}, [0, 1, 5]),
])
def test_native_exports_and_selection_replay(client, tmp_path, incoming, outgoing, shape, extra, selected):
    source_path = tmp_path / f"source.{incoming}"
    data = make_las(source_path)
    source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    url, auth, source = open_source(client, source_path)
    assert source["sha256"] == source_digest and source["result"]["point_count"] == len(POINTS)
    assert source["result"]["axis_units"] == []
    assert client.get(url).status_code == 404
    preview = client.get(url + "/preview?quality=draft", headers=auth)
    binary = np.frombuffer(preview.content, PREVIEW_DTYPE)
    assert preview.headers["content-type"] == "application/octet-stream"
    assert np.array_equal(binary["xyz"], POINTS)

    body = crop_payload(source, outgoing, shape, **extra)
    mask = client.post(url + "/preview-crop", json={"selection": body["selection"], "quality": "draft"}, headers=auth)
    assert np.flatnonzero(np.frombuffer(mask.content, dtype="u1")).tolist() == selected
    job = start_job(client, url, auth, body)
    assert status(client, job, auth)["result"]["point_count"] == len(selected)
    exported_path = tmp_path / f"exported.{outgoing}"
    exported_path.write_bytes(download(client, job, auth, "output"))
    exported = laspy.read(exported_path)
    assert np.array_equal(exported.points.array, data.points.array[selected])
    assert np.array_equal(exported.header.offsets, data.header.offsets)
    assert np.array_equal(exported.header.scales, data.header.scales)
    info = json.loads(download(client, job, auth, "selection"))
    assert info["source_filename"] == source_path.name
    assert info["schema_version"] == 1
    assert "input_file" not in info and "output_file" not in info
    assert client.post(url + "/jobs", json={**body, "source_sha256": "0" * 64}, headers=auth).status_code == 409
    replay = start_job(client, url, auth, {k: info[k] for k in ("selection", "output_format", "source_sha256", "accept_derivative")})
    assert status(client, replay, auth)["result"]["point_count"] == len(selected)
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_digest


def test_gaussian_ply_and_conversion_warning(client, tmp_path):
    path = tmp_path / "gaussian.ply"
    names = ["x", "y", "z", "f_dc_0", "opacity", "scale_0", "rot_0"]
    vertices = np.zeros(len(POINTS), dtype=[(name, ">f4") for name in names])
    vertices["x"], vertices["y"], vertices["z"] = POINTS.T
    vertices["opacity"], vertices["f_dc_0"] = np.arange(len(POINTS)), np.linspace(-1, 1, len(POINTS))
    PlyData([PlyElement.describe(vertices, "vertex")], byte_order=">").write(path)
    url, auth, source = open_source(client, path)
    assert "Gaussian" in source["result"]["classification"]
    assert client.post(url + "/jobs", json=crop_payload(source, "las"), headers=auth).status_code == 422
    job = start_job(client, url, auth, crop_payload(source, "ply"))
    assert status(client, job, auth)["status"] == "completed"
    out = tmp_path / "out.ply"
    out.write_bytes(download(client, job, auth, "output"))
    assert np.array_equal(PlyData.read(out)["vertex"].data, vertices[[0, 1, 3]])

    native = tmp_path / "native.las"
    make_las(native)
    url, auth, source = open_source(client, native)
    body = crop_payload(source, "ply")
    assert client.post(url + "/jobs", json=body, headers=auth).status_code == 422
    job = start_job(client, url, auth, {**body, "accept_derivative": True})
    assert status(client, job, auth)["status"] == "completed"
    converted = json.loads(download(client, job, auth, "selection"))
    assert converted["derivative"]["native_header_records_in_output"] is False


def test_bounded_preview_and_full_resolution_export(client, tmp_path):
    path = tmp_path / "cloud.las"
    data = make_las(path, np.tile(POINTS, (4300, 1)))
    url, auth, inspected = open_source(client, path)
    assert inspected["result"]["preview_counts"] == {"draft": 25_000, "standard": 30_100, "high": 30_100}
    assert len(client.get(url + "/preview?quality=draft", headers=auth).content) == 28 * 25_000
    body = crop_payload(inspected, "las")
    body["selection"]["radius"] = 5
    preview_payload = {"selection": body["selection"], "quality": "draft", "include_full_count": True}
    preview = client.post(url + "/preview-crop", json=preview_payload,
                          headers={**auth, "Origin": "http://localhost:3000"})
    assert len(preview.content) == sum(preview.content) == 25_000
    assert preview.headers["access-control-expose-headers"] == "X-Lidar-Count-Id"
    count_id = preview.headers["x-lidar-count-id"]
    count_url = url + "/preview-count/" + count_id
    assert client.get(count_url).status_code == 404
    assert status(client, count_url, auth)["result"]["point_count"] == 30_100
    assert not list((tmp_path / "lidar").rglob("crop.las"))
    repeated = client.post(url + "/preview-crop", json=preview_payload, headers=auth)
    assert repeated.headers["x-lidar-count-id"] == count_id
    full_sample = client.post(url + "/preview-crop", json={**preview_payload, "quality": "high"}, headers=auth)
    assert "x-lidar-count-id" not in full_sample.headers
    assert sum(full_sample.content) == 30_100
    job = start_job(client, url, auth, body)
    assert status(client, job, auth)["result"]["point_count"] == 30_100
    path = tmp_path / "cropped.las"
    path.write_bytes(download(client, job, auth, "output"))
    assert np.array_equal(laspy.read(path).points.array, data.points.array)


def test_new_preview_supersedes_running_count(client, tmp_path, monkeypatch):
    path = tmp_path / "large.laz"
    make_las(path, np.tile(POINTS, (4000, 1)))
    url, auth, inspected = open_source(client, path)
    entered = Event()
    real_count = lidar_service.count_selection

    def pause_first(source, selection, progress, cancelled):
        if selection.radius == 1:
            entered.set()
            while not cancelled():
                time.sleep(.005)
        return real_count(source, selection, progress, cancelled)

    monkeypatch.setattr(lidar_service, "count_selection", pause_first)
    selection = crop_payload(inspected, "laz")["selection"]
    payload = {"selection": selection, "quality": "draft", "include_full_count": True}
    first = client.post(url + "/preview-crop", json=payload, headers=auth)
    assert entered.wait(3)
    selection["radius"] = 5
    final = client.post(url + "/preview-crop", json=payload, headers=auth)
    assert client.get(url + "/preview-count/" + first.headers["x-lidar-count-id"], headers=auth).status_code == 404
    assert status(client, url + "/preview-count/" + final.headers["x-lidar-count-id"], auth)["result"]["point_count"] == 28_000


def test_cancel_does_not_publish_partial_export(client, tmp_path, monkeypatch):
    path = tmp_path / "source.las"
    make_las(path)
    url, auth, inspected = open_source(client, path)
    entered = Event()

    def delayed(source_path, output, request, expected_hash, progress, cancelled):
        output.write_bytes(b"partially written file")
        entered.set()
        while not cancelled():
            time.sleep(.005)
        progress(30)  # Raises CropCancelled and exercises worker cleanup.

    monkeypatch.setattr(lidar_service, "export_selection", delayed)
    job = start_job(client, url, auth, crop_payload(inspected, "las"))
    assert entered.wait(3)
    assert client.post(job + "/cancel", headers=auth).json()["cancel_requested"] is True
    assert status(client, job, auth)["status"] == "cancelled"
    assert client.post(job + "/download/output", headers=auth).status_code == 409
    assert not list((tmp_path / "lidar").rglob("crop.las"))


def test_reject_wrong_formats_and_incomplete_upload(client, tmp_path, monkeypatch):
    path = tmp_path / "fake.las"
    assert upload(client, path, b"x", declared_size=2).status_code == 400
    truncated = client.post(f"{API}/sources", content=iter([b"LASF"]), headers={
        "Content-Type": "application/octet-stream", "X-Lidar-Filename": path.name, "X-Lidar-Size": "40",
    })
    assert truncated.status_code == 400 and truncated.json()["detail"] == "Upload is incomplete."
    assert not list((tmp_path / "lidar").rglob("upload.part"))
    response = upload(client, path, b"this is not a LAS file")
    doc = response.json()
    url = f"{API}/sources/{doc['id']}"
    auth = {"Authorization": f"Bearer {doc['token']}"}
    assert status(client, url, auth)["status"] == "failed"
    assert client.get(url + "/preview", headers=auth).status_code == 409
    assert not list((tmp_path / "lidar").rglob("source.las"))
    assert client.delete(url, headers=auth).status_code == 204

    monkeypatch.setattr(settings, "max_upload_size_mb", 1)
    assert upload(client, path, b"x", declared_size=1024**2 + 1).status_code == 413
    response = client.post(f"{API}/sources", content=b"x", headers={
        "Content-Type": "application/octet-stream", "X-Lidar-Filename": "..%2Ffake.las", "X-Lidar-Size": "1",
    })
    assert response.status_code == 400


def test_expired_source_cleans_preview_and_storage(client, tmp_path):
    source_path = tmp_path / "expire.las"
    make_las(source_path)
    url, auth, value = open_source(client, source_path)
    service = client.app.state.lidar_service
    with service.lock:
        source = service.sessions[value["id"]]
        files = source.path.parent
        assert (files / "preview-high.bin").is_file()
        source.used -= (settings.uploaded_job_ttl_hours + 1) * 3600
    service.cleanup()
    assert not files.exists()
    assert client.get(url, headers=auth).status_code == 404
