"""Local-only web entry point for the offline BankOCR pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as email_policy
from html import escape
import argparse
import json
from pathlib import Path, PurePosixPath
import threading
import tempfile
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
import re
import zipfile
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4


DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
EXPORT_SUFFIXES = (
    ".xlsx",
    ".searchable.pdf",
    ".comparison.pdf",
    ".summary.json",
    ".export-manifest.json",
)
JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ServerConfig:
    bind_host: str = "127.0.0.1"
    port: int = 18081
    work_dir: Path = Path("work/server-data")
    model_dir: Path = Path("models")
    model_manifest: Path = Path("models/manifest.json")
    template_dir: Path = Path("templates/known")
    font_file: Path = Path("fonts/msyh.ttc")
    dpi: int = 150
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES

    def __post_init__(self) -> None:
        if not self.bind_host:
            raise ValueError("bind_host must not be empty")
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.dpi <= 0:
            raise ValueError("dpi must be positive")
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")


@dataclass(slots=True)
class JobRecord:
    job_id: str
    original_filename: str
    job_dir: Path
    status: str = "queued"
    error: str | None = None
    output_files: tuple[str, ...] = ()
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.job_id,
            "filename": self.original_filename,
            "status": self.status,
            "error": self.error,
            "output_files": list(self.output_files),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ServerRuntime:
    """Thread-safe in-memory job index backed by per-job directories."""

    def __init__(
        self,
        config: ServerConfig,
        runner: Callable[[Path, Path], None],
    ) -> None:
        self.config = config
        self.runner = runner
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bankocr")

    def submit(self, original_filename: str, content: bytes) -> JobRecord:
        safe_name = Path(original_filename).name or "upload.pdf"
        job_id = uuid4().hex[:12]
        job_dir = self.config.work_dir / "jobs" / job_id
        output_dir = job_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=False)
        (job_dir / safe_name).write_bytes(content)
        record = JobRecord(job_id=job_id, original_filename=safe_name, job_dir=job_dir)
        with self._lock:
            self._jobs[job_id] = record
        self._executor.submit(self._run, job_id)
        return self.snapshot(job_id)

    def snapshot(self, job_id: str) -> JobRecord:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                raise KeyError(job_id)
            return _copy_record(record)

    def list_snapshots(self) -> tuple[JobRecord, ...]:
        with self._lock:
            records = tuple(_copy_record(record) for record in self._jobs.values())
        return tuple(sorted(records, key=lambda record: record.created_at, reverse=True))

    def output_path(self, job_id: str, filename: str) -> Path | None:
        if not JOB_ID_PATTERN.fullmatch(job_id):
            return None
        if not filename or PurePosixPath(filename).name != filename:
            return None
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None or filename not in record.output_files:
                return None
            path = (record.job_dir / "output" / filename).resolve()
            output_root = (record.job_dir / "output").resolve()
        if path.parent != output_root or not path.is_file():
            return None
        return path

    def archive_members(self, job_id: str) -> tuple[str, tuple[Path, ...]]:
        """Return the completed job's validated output files for ZIP creation."""
        if not JOB_ID_PATTERN.fullmatch(job_id):
            raise KeyError(job_id)
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                raise KeyError(job_id)
            if record.status != "completed":
                raise RuntimeError("任务尚未完成")
            original_filename = record.original_filename
            filenames = record.output_files
            output_root = (record.job_dir / "output").resolve()

        members: list[Path] = []
        for filename in filenames:
            if not filename or PurePosixPath(filename).name != filename:
                raise ValueError("结果文件名无效")
            path = (output_root / filename).resolve()
            if path.parent != output_root or not path.is_file():
                raise FileNotFoundError("结果文件不存在")
            members.append(path)
        return original_filename, tuple(members)

    def queue_size(self) -> int:
        with self._lock:
            return sum(record.status in {"queued", "processing"} for record in self._jobs.values())

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _run(self, job_id: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.status = "processing"
            record.updated_at = _utc_now()
        try:
            record = self.snapshot(job_id)
            source = record.job_dir / record.original_filename
            output = record.job_dir / "output"
            self.runner(source, output)
            files = tuple(sorted(path.name for path in output.iterdir() if _is_export_file(path)))
            if not files:
                raise RuntimeError("处理完成但没有生成结果文件")
            with self._lock:
                current = self._jobs[job_id]
                current.status = "completed"
                current.output_files = files
                current.updated_at = _utc_now()
        except BaseException as exc:  # noqa: BLE001 - worker must record every failure
            with self._lock:
                current = self._jobs.get(job_id)
                if current is not None:
                    current.status = "failed"
                    current.error = _error_text(exc)
                    current.updated_at = _utc_now()


class BankOCRHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, runtime: ServerRuntime) -> None:
        self.runtime = runtime
        super().__init__(address, BankOCRRequestHandler)


class BankOCRRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BankOCRServer/0.1"

    @property
    def runtime(self) -> ServerRuntime:
        return self.server.runtime  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP API
        route = urlsplit(self.path).path
        if route == "/":
            self._send_html(_INDEX_HTML)
            return
        if route == "/healthz":
            self._send_json({"status": "ok", "queue_size": self.runtime.queue_size()})
            return
        if route == "/api/jobs":
            self._send_json({"jobs": [job.to_dict() for job in self.runtime.list_snapshots()]})
            return
        match = re.fullmatch(r"/api/jobs/([0-9a-f]{12})", route)
        if match:
            try:
                self._send_json(self.runtime.snapshot(match.group(1)).to_dict())
            except KeyError:
                self._send_json({"error": "任务不存在"}, status=404)
            return
        match = re.fullmatch(r"/download/([0-9a-f]{12})/all\.zip", route)
        if match:
            try:
                self._send_archive(match.group(1))
            except KeyError:
                self._send_json({"error": "任务不存在"}, status=404)
            except RuntimeError:
                self._send_json({"error": "任务尚未完成"}, status=409)
            except (FileNotFoundError, OSError, ValueError):
                self._send_json({"error": "结果文件暂时不可用"}, status=500)
            return
        match = re.fullmatch(r"/download/([0-9a-f]{12})/(.+)", route)
        if match:
            filename = unquote(match.group(2))
            path = self.runtime.output_path(match.group(1), filename)
            if path is None:
                self._send_json({"error": "结果文件不存在"}, status=404)
                return
            self._send_file(path)
            return
        self._send_json({"error": "页面不存在"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP API
        route = urlsplit(self.path).path
        if route != "/upload":
            self._send_json({"error": "接口不存在"}, status=404)
            return
        content_length = self.headers.get("Content-Length")
        try:
            body_length = int(content_length or "-1")
        except ValueError:
            body_length = -1
        if body_length < 0:
            self._send_json({"error": "上传请求缺少文件大小"}, status=411)
            return
        if body_length > self.runtime.config.max_upload_bytes:
            self._send_json({"error": "文件超过大小限制"}, status=413)
            return
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            self._send_json({"error": "请使用 PDF 文件上传表单"}, status=415)
            return
        body = self.rfile.read(body_length)
        if len(body) != body_length:
            self._send_json({"error": "上传内容不完整"}, status=400)
            return
        try:
            filename, content = _parse_upload(content_type, body)
            _validate_pdf(filename, content)
            record = self.runtime.submit(filename, content)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except OSError:
            self._send_json({"error": "服务器无法保存上传文件"}, status=500)
            return
        self._send_json(record.to_dict(), status=202)

    def _send_json(self, payload: dict[str, object], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, path: Path) -> None:
        size = path.stat().st_size
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        ascii_name = path.name.encode("ascii", "ignore").decode("ascii") or "download"
        utf8_name = quote(path.name, safe="")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{escape(ascii_name)}"; filename*=UTF-8\'\'{utf8_name}',
        )
        self.end_headers()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                self.wfile.write(chunk)

    def _send_archive(self, job_id: str) -> None:
        original_filename, members = self.runtime.archive_members(job_id)
        stem = Path(original_filename).stem
        safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip(" .")
        safe_stem = safe_stem or "bankocr-results"
        archive_name = f"{safe_stem}-全部结果.zip"
        ascii_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", safe_stem).strip(" ._-")
        ascii_name = f"{ascii_stem or 'bankocr-results'}-results.zip"

        with tempfile.TemporaryFile() as handle:
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in members:
                    archive.write(path, arcname=path.name)
            size = handle.tell()
            handle.seek(0)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(size))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{escape(ascii_name)}"; '
                f"filename*=UTF-8''{quote(archive_name, safe='')}",
            )
            self.end_headers()
            while chunk := handle.read(1024 * 1024):
                self.wfile.write(chunk)

    def log_message(self, format: str, *args) -> None:
        print(f"[bankocr-server] {self.address_string()} - {format % args}")


def create_server(
    config: ServerConfig,
    *,
    runner: Callable[[Path, Path], None] | None = None,
) -> tuple[BankOCRHTTPServer, ServerRuntime]:
    _validate_resources(config)
    config.work_dir.mkdir(parents=True, exist_ok=True)
    runtime = ServerRuntime(config, runner or _make_cli_runner(config))
    try:
        server = BankOCRHTTPServer((config.bind_host, config.port), runtime)
    except BaseException:
        runtime.shutdown()
        raise
    return server, runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the local-only BankOCR web service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--work-dir", type=Path, default=Path("work/server-data"))
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--template-dir", type=Path, required=True)
    parser.add_argument("--font-file", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--max-upload-mib", type=int, default=100)
    args = parser.parse_args(argv)
    config = ServerConfig(
        bind_host=args.host,
        port=args.port,
        work_dir=args.work_dir,
        model_dir=args.model_dir,
        model_manifest=args.model_manifest,
        template_dir=args.template_dir,
        font_file=args.font_file,
        dpi=args.dpi,
        max_upload_bytes=args.max_upload_mib * 1024 * 1024,
    )
    try:
        server, runtime = create_server(config)
    except (FileNotFoundError, ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"BankOCR server listening on http://{config.bind_host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        runtime.shutdown()
    return 0


def _validate_resources(config: ServerConfig) -> None:
    checks = (
        ("model_dir", config.model_dir, True),
        ("model_manifest", config.model_manifest, False),
        ("template_dir", config.template_dir, True),
        ("font_file", config.font_file, False),
    )
    for name, path, is_dir in checks:
        if not path.exists() or (is_dir and not path.is_dir()) or (not is_dir and not path.is_file()):
            raise FileNotFoundError(f"{name} does not exist: {path}")


def _make_cli_runner(config: ServerConfig) -> Callable[[Path, Path], None]:
    def run(source: Path, output: Path) -> None:
        from bankocr.cli import main as cli_main

        args = [
            str(source),
            "--output-dir",
            str(output),
            "--project-db",
            str(source.parent / "project.sqlite3"),
            "--dpi",
            str(config.dpi),
            "--model-dir",
            str(config.model_dir),
            "--model-manifest",
            str(config.model_manifest),
            "--template-dir",
            str(config.template_dir),
            "--font-file",
            str(config.font_file),
        ]
        return_code = cli_main(args)
        if return_code != 0:
            raise RuntimeError(f"BankOCR CLI exited with code {return_code}")

    return run


def _parse_upload(content_type: str, body: bytes) -> tuple[str, bytes]:
    headers = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n"
        "\r\n"
    ).encode("utf-8")
    message = BytesParser(policy=email_policy).parsebytes(headers + body)
    if not message.is_multipart():
        raise ValueError("上传表单格式不正确")
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if part.get_param("name", header="Content-Disposition") != "file":
            continue
        filename = part.get_filename() or "upload.pdf"
        content = part.get_payload(decode=True) or b""
        return filename, content
    raise ValueError("没有找到 PDF 文件")


def _validate_pdf(filename: str, content: bytes) -> None:
    if Path(filename).suffix.casefold() != ".pdf":
        raise ValueError("只允许上传 PDF 文件")
    if not content.startswith(b"%PDF-"):
        raise ValueError("上传文件不是有效的 PDF")


def _is_export_file(path: Path) -> bool:
    return path.is_file() and path.name.casefold().endswith(EXPORT_SUFFIXES)


def _copy_record(record: JobRecord) -> JobRecord:
    return JobRecord(
        job_id=record.job_id,
        original_filename=record.original_filename,
        job_dir=record.job_dir,
        status=record.status,
        error=record.error,
        output_files=record.output_files,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, SystemExit):
        return f"处理程序退出（代码 {exc.code}）"
    return f"{type(exc).__name__}: {exc}".strip()


_INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BankOCR 银行流水处理</title>
  <style>
    :root { color-scheme: light; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { max-width: 1080px; margin: 32px auto; padding: 0 20px; color: #243447; background: #f5f7fa; line-height: 1.5; }
    main { background: white; border-radius: 16px; padding: 32px; box-shadow: 0 8px 30px #17324d12; }
    h1 { margin: 0; color: #164e78; font-size: 30px; letter-spacing: .01em; }
    h2 { margin: 28px 0 12px; color: #243447; font-size: 21px; }
    h3, h4, p { margin-top: 0; }
    .hint { color: #667085; }
    .intro { margin: 8px 0 24px; color: #667085; }
    form { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 18px; background: #eef6fb; border: 1px solid #d8eaf5; border-radius: 10px; }
    input[type="file"] { min-width: 260px; max-width: 100%; }
    button { min-height: 40px; background: #1f78b4; color: white; border: 0; padding: 10px 18px; border-radius: 7px; cursor: pointer; font-weight: 600; }
    button:disabled { background: #9aa7b2; cursor: wait; }
    #message { min-height: 24px; margin-top: 12px; color: #36566e; }
    .job { border: 1px solid #d9e2ec; border-radius: 12px; padding: 18px; margin-top: 14px; background: #fff; }
    .job-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
    .job-title { min-width: 0; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .job-title strong { overflow-wrap: anywhere; }
    .status { font-weight: 700; white-space: nowrap; }
    .queued, .processing { color: #9a6700; } .completed { color: #137333; } .failed { color: #b3261e; }
    .download-all { display: inline-flex; align-items: center; justify-content: center; min-height: 40px; padding: 9px 15px; border-radius: 7px; background: #1769aa; color: white; text-decoration: none; font-weight: 700; white-space: nowrap; transition: background-color 160ms ease, box-shadow 160ms ease, transform 160ms ease; }
    .download-all:hover { background: #125585; box-shadow: 0 3px 8px #1769aa33; transform: translateY(-1px); }
    .download-all:focus-visible, .file-link:focus-visible { outline: 3px solid #8bc7ee; outline-offset: 2px; }
    .result-groups { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
    .file-group { min-width: 0; padding: 14px; border: 1px solid #e2e8f0; border-radius: 10px; background: #f8fafc; }
    .file-group h3 { margin-bottom: 2px; color: #29465c; font-size: 16px; }
    .file-group p { margin-bottom: 10px; color: #7a8896; font-size: 13px; }
    .file-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }
    .file-link { min-width: 0; display: block; padding: 10px 11px; border: 1px solid #d7e1ea; border-radius: 8px; background: white; color: #1769aa; text-decoration: none; transition: background-color 160ms ease, border-color 160ms ease, box-shadow 160ms ease; }
    .file-link:hover { border-color: #8fc2df; background: #f3faff; box-shadow: 0 2px 6px #17324d10; }
    .file-label { display: block; font-weight: 700; }
    .file-name { display: block; overflow: hidden; color: #7a8896; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
    @media (max-width: 700px) {
      body { margin: 18px auto; padding: 0 12px; }
      main { padding: 22px 18px; }
      h1 { font-size: 25px; }
      .job-head { align-items: stretch; flex-direction: column; }
      .download-all { width: 100%; }
      .result-groups { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
<main>
  <h1>BankOCR 银行流水处理</h1>
  <p class="intro">选择 PDF 后点击“开始处理”。处理完成后，可以下载全部结果，也可以按用途分别打开。</p>
  <form id="upload-form" enctype="multipart/form-data">
    <input id="file" name="file" type="file" accept="application/pdf,.pdf" required>
    <button id="submit" type="submit">开始处理</button>
  </form>
  <div id="message"></div>
  <section id="jobs"><h2>处理记录</h2><p class="hint">暂无任务</p></section>
</main>
<script>
const form = document.getElementById('upload-form');
const button = document.getElementById('submit');
const message = document.getElementById('message');
const jobs = document.getElementById('jobs');
let activeId = null;
const resultGroups = [
  {key: 'use', title: '直接使用', hint: '用于整理、搜索和统计', files: []},
  {key: 'compare', title: '和 PDF 对照', hint: '用于逐页查看原文位置', files: []},
  {key: 'review', title: '人工复核', hint: '只列出需要人工确认的项目', files: []},
  {key: 'audit', title: '处理记录', hint: '保存处理过程和文件校验信息', files: []},
];

function describeFile(name) {
  if (name.endsWith('.pdf-layout.xlsx')) return ['compare', 'PDF 原样 Excel'];
  if (name.endsWith('.comparison.pdf')) return ['compare', '核对 PDF'];
  if (name.endsWith('.searchable.pdf')) return ['compare', '可搜索 PDF'];
  if (name.endsWith('.review.xlsx')) return ['review', '人工复核表'];
  if (name.endsWith('.summary.json')) return ['audit', '处理摘要'];
  if (name.endsWith('.export-manifest.json')) return ['audit', '导出清单'];
  if (name.endsWith('.xlsx')) return ['use', '普通 Excel'];
  return ['audit', '其他结果'];
}
form.addEventListener('submit', async (event) => {
  event.preventDefault(); button.disabled = true; message.textContent = '正在上传…';
  try {
    const response = await fetch('/upload', {method: 'POST', body: new FormData(form)});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '上传失败');
    activeId = payload.id; message.textContent = '已加入处理队列。'; await refresh();
  } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
function label(status) { return ({queued:'排队中', processing:'处理中', completed:'已完成', failed:'处理失败'})[status] || status; }
function text(parent, value) { parent.appendChild(document.createTextNode(String(value ?? ''))); }
function makeFileLink(jobId, file) {
  const link = document.createElement('a'); link.className = 'file-link';
  link.href = '/download/' + encodeURIComponent(jobId) + '/' + encodeURIComponent(file.name);
  link.title = file.name;
  const labelNode = document.createElement('span'); labelNode.className = 'file-label'; text(labelNode, file.label);
  const nameNode = document.createElement('span'); nameNode.className = 'file-name'; text(nameNode, file.name);
  link.appendChild(labelNode); link.appendChild(nameNode);
  return link;
}

function makeGroup(jobId, group) {
  const section = document.createElement('section'); section.className = 'file-group';
  const title = document.createElement('h3'); text(title, group.title); section.appendChild(title);
  const hint = document.createElement('p'); text(hint, group.hint); section.appendChild(hint);
  const list = document.createElement('div'); list.className = 'file-list';
  for (const file of group.files) list.appendChild(makeFileLink(jobId, file));
  section.appendChild(list);
  return section;
}
async function refresh() {
  const response = await fetch('/api/jobs', {cache: 'no-store'}); const payload = await response.json();
  jobs.replaceChildren();
  const title = document.createElement('h2'); text(title, '处理记录'); jobs.appendChild(title);
  if (!payload.jobs.length) { const empty = document.createElement('p'); empty.className = 'hint'; text(empty, '暂无任务'); jobs.appendChild(empty); return; }
  for (const job of payload.jobs) {
    const div = document.createElement('div'); div.className = 'job';
    const heading = document.createElement('div'); heading.className = 'job-head';
    const jobTitle = document.createElement('div'); jobTitle.className = 'job-title';
    const filename = document.createElement('strong'); text(filename, job.filename); jobTitle.appendChild(filename);
    const safeStatus = ['queued', 'processing', 'completed', 'failed'].includes(job.status) ? job.status : 'unknown';
    const status = document.createElement('span'); status.className = 'status ' + safeStatus; text(status, label(job.status));
    jobTitle.appendChild(status); heading.appendChild(jobTitle);
    if (job.status === 'completed') {
      const archive = document.createElement('a'); archive.className = 'download-all';
      archive.href = '/download/' + encodeURIComponent(job.id) + '/all.zip'; archive.title = '下载此任务的全部结果（不包含原始 PDF）'; text(archive, '下载全部结果 ZIP');
      heading.appendChild(archive);
    }
    div.appendChild(heading);
    if (job.error) { const error = document.createElement('p'); text(error, job.error); div.appendChild(error); }
    if ((job.output_files || []).length) {
      const groupMap = new Map(resultGroups.map(group => [group.key, {...group, files: []}]));
      for (const rawName of job.output_files) {
        const name = String(rawName ?? '');
        const [key, fileLabel] = describeFile(name);
        const group = groupMap.get(key) || groupMap.get('audit');
        group.files.push({name, label: fileLabel});
      }
      const groups = document.createElement('div'); groups.className = 'result-groups';
      for (const group of resultGroups) {
        const populated = groupMap.get(group.key);
        if (populated.files.length) groups.appendChild(makeGroup(job.id, populated));
      }
      div.appendChild(groups);
    }
    jobs.appendChild(div);
  }
}
refresh(); setInterval(refresh, 2000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    raise SystemExit(main())
