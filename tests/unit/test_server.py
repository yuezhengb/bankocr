from __future__ import annotations

import io
import http.client
import json
from pathlib import Path
import threading
import time
import zipfile

import pytest

from bankocr.server import ServerConfig, create_server


def _config(tmp_path: Path, *, max_upload_bytes: int = 100 * 1024 * 1024) -> ServerConfig:
    model_dir = tmp_path / "models"
    template_dir = tmp_path / "templates"
    model_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    model_manifest = model_dir / "manifest.json"
    model_manifest.write_text("{}", encoding="utf-8")
    font_file = tmp_path / "font.ttc"
    font_file.write_bytes(b"font")
    return ServerConfig(
        bind_host="127.0.0.1",
        port=0,
        work_dir=tmp_path / "server-data",
        model_dir=model_dir,
        model_manifest=model_manifest,
        template_dir=template_dir,
        font_file=font_file,
        max_upload_bytes=max_upload_bytes,
    )


def _multipart(filename: str, content: bytes) -> tuple[bytes, dict[str, str]]:
    boundary = b"bankocr-test-boundary"
    body = (
        b"--" + boundary + b"\r\n"
        + b'Content-Disposition: form-data; name="file"; filename="'
        + filename.encode("utf-8")
        + b'"\r\nContent-Type: application/pdf\r\n\r\n'
        + content
        + b"\r\n--"
        + boundary
        + b"--\r\n"
    )
    return body, {
        "Content-Type": f"multipart/form-data; boundary={boundary.decode()}"
    }


def _request(port: int, method: str, path: str, body: bytes | None = None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    status = response.status
    response_headers = dict(response.getheaders())
    connection.close()
    return status, response_headers, payload


def test_server_uploads_pdf_queues_job_and_downloads_layout_excel(tmp_path: Path) -> None:
    def fake_runner(source: Path, output: Path) -> None:
        assert source.read_bytes().startswith(b"%PDF")
        output.mkdir(parents=True, exist_ok=True)
        (output / "statement.xlsx").write_bytes(b"structured")
        (output / "statement.pdf-layout.xlsx").write_bytes(b"layout")
        time.sleep(0.02)

    server, runtime = create_server(_config(tmp_path), runner=fake_runner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        status, _, health = _request(port, "GET", "/healthz")
        assert status == 200
        assert json.loads(health)["status"] == "ok"

        body, headers = _multipart("statement.pdf", b"%PDF-1.7 fake")
        status, _, uploaded = _request(port, "POST", "/upload", body, headers)
        assert status == 202
        job = json.loads(uploaded)
        job_id = job["id"]

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, _, payload = _request(port, "GET", f"/api/jobs/{job_id}")
            current = json.loads(payload)
            if current["status"] == "completed":
                break
            time.sleep(0.02)
        assert current["status"] == "completed"
        assert "statement.pdf-layout.xlsx" in current["output_files"]

        status, _, downloaded = _request(
            port,
            "GET",
            f"/download/{job_id}/statement.pdf-layout.xlsx",
        )
        assert status == 200
        assert downloaded == b"layout"

        status, _, rejected = _request(port, "GET", f"/download/{job_id}/..%2Finput.pdf")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()
        runtime.shutdown()
        thread.join(timeout=2)


def test_server_downloads_all_results_as_zip_without_source(tmp_path: Path) -> None:
    names = (
        "statement.xlsx",
        "statement.pdf-layout.xlsx",
        "statement.comparison.pdf",
        "statement.searchable.pdf",
        "statement.review.xlsx",
        "statement.summary.json",
        "statement.export-manifest.json",
    )

    def fake_runner(source: Path, output: Path) -> None:
        output.mkdir(parents=True, exist_ok=True)
        for name in names:
            (output / name).write_bytes(name.encode("ascii"))
        (output / "internal.tmp").write_bytes(b"must not be exported")

    server, runtime = create_server(_config(tmp_path), runner=fake_runner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body, headers = _multipart("statement.pdf", b"%PDF-1.7 fake")
        status, _, uploaded = _request(
            server.server_address[1], "POST", "/upload", body, headers
        )
        assert status == 202
        job_id = json.loads(uploaded)["id"]

        deadline = time.monotonic() + 5
        current = None
        while time.monotonic() < deadline:
            status, _, payload = _request(
                server.server_address[1], "GET", f"/api/jobs/{job_id}"
            )
            current = json.loads(payload)
            if current["status"] == "completed":
                break
            time.sleep(0.02)
        assert current is not None
        assert current["status"] == "completed"

        status, response_headers, payload = _request(
            server.server_address[1], "GET", f"/download/{job_id}/all.zip"
        )
        assert status == 200
        assert response_headers["Content-Type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            assert archive.namelist() == sorted(names)
            assert all(archive.read(name) == name.encode("ascii") for name in names)
            assert "statement.pdf" not in archive.namelist()
            assert "internal.tmp" not in archive.namelist()

        status, _, _ = _request(
            server.server_address[1], "GET", "/download/000000000000/all.zip"
        )
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()
        runtime.shutdown()
        thread.join(timeout=2)


def test_server_rejects_zip_download_while_job_is_processing(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking_runner(source: Path, output: Path) -> None:
        started.set()
        release.wait(timeout=5)
        output.mkdir(parents=True, exist_ok=True)
        (output / "statement.xlsx").write_bytes(b"structured")

    server, runtime = create_server(_config(tmp_path), runner=blocking_runner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body, headers = _multipart("statement.pdf", b"%PDF-1.7 fake")
        status, _, uploaded = _request(
            server.server_address[1], "POST", "/upload", body, headers
        )
        assert status == 202
        job_id = json.loads(uploaded)["id"]
        assert started.wait(timeout=2)

        status, _, payload = _request(
            server.server_address[1], "GET", f"/download/{job_id}/all.zip"
        )
        assert status == 409
        assert json.loads(payload)["error"] == "任务尚未完成"
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        runtime.shutdown()
        thread.join(timeout=2)


def test_server_rejects_non_pdf_and_oversized_upload(tmp_path: Path) -> None:
    server, runtime = create_server(_config(tmp_path, max_upload_bytes=512), runner=lambda *_: None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        body, headers = _multipart("notes.txt", b"not a pdf")
        status, _, _ = _request(port, "POST", "/upload", body, headers)
        assert status == 400

        body, headers = _multipart("large.pdf", b"%PDF-" + b"x" * 100)
        status, _, _ = _request(port, "POST", "/upload", body, headers)
        assert status == 202
    finally:
        server.shutdown()
        server.server_close()
        runtime.shutdown()
        thread.join(timeout=2)

    small_config = _config(tmp_path / "small", max_upload_bytes=32)
    server, runtime = create_server(small_config, runner=lambda *_: None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body, headers = _multipart("large.pdf", b"%PDF-" + b"x" * 100)
        status, _, _ = _request(server.server_address[1], "POST", "/upload", body, headers)
        assert status == 413
    finally:
        server.shutdown()
        server.server_close()
        runtime.shutdown()
        thread.join(timeout=2)


def test_server_requires_local_resources(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config = ServerConfig(
        bind_host=config.bind_host,
        port=config.port,
        work_dir=config.work_dir,
        model_dir=tmp_path / "missing-models",
        model_manifest=config.model_manifest,
        template_dir=config.template_dir,
        font_file=config.font_file,
    )

    with pytest.raises(FileNotFoundError, match="model_dir"):
        create_server(config)


def test_server_page_renders_job_fields_as_text_nodes(tmp_path: Path) -> None:
    server, runtime = create_server(_config(tmp_path), runner=lambda *_: None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, page = _request(server.server_address[1], "GET", "/")
        html = page.decode("utf-8")
        assert status == 200
        assert "document.createTextNode" in html
        assert "job.filename + '</strong>" not in html
        assert "下载全部结果 ZIP" in html
        assert "直接使用" in html
        assert "和 PDF 对照" in html
        assert "人工复核" in html
        assert "处理记录" in html
        assert "/all.zip" in html
    finally:
        server.shutdown()
        server.server_close()
        runtime.shutdown()
        thread.join(timeout=2)
