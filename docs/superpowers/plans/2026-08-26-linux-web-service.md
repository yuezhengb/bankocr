# Linux 网页服务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Linux VPS 上提供一个仅通过 SSH 隧道访问的 BankOCR 网页入口，复用现有 CLI 导出全部结果。

**Architecture:** 用 Python 标准库 `ThreadingHTTPServer` 提供上传页面、任务状态和结果下载；后台用单线程队列调用现有 `bankocr.cli.main`，不复制 OCR 或导出逻辑。服务默认绑定 `127.0.0.1:18081`，systemd 负责启动和重启。

**Tech Stack:** Python 3.11+；标准库 HTTP、队列、线程、JSON；现有 PyMuPDF、OpenCV、RapidOCR、ONNX Runtime、openpyxl；pytest；systemd。

## Global Constraints

- Do not change other services already running on the host.
- 服务默认只监听 `127.0.0.1:18081`。
- 同一时间最多一个 OCR 任务。
- 上传文件必须是 PDF，默认不超过 100 MiB。
- 结果文件必须位于任务目录，下载接口只允许已生成的白名单文件。
- 原始 PDF 永不覆盖。
- 运行时不下载模型。
- Windows GUI 和现有 CLI 行为不改变。

---

### Task 1: 实现标准库网页服务核心

**Files:**
- Create: `src/bankocr/server.py`
- Test: `tests/unit/test_server.py`

**Interfaces:**
- `create_server(config: ServerConfig, runner: Callable[[Path, Path], None] | None = None) -> tuple[ThreadingHTTPServer, ServerRuntime]`
- `ServerConfig(bind_host: str, port: int, work_dir: Path, model_dir: Path, model_manifest: Path, template_dir: Path, font_file: Path, dpi: int = 150, max_upload_bytes: int = 100 * 1024 * 1024)`
- HTTP API: `GET /healthz`、`GET /`、`POST /upload`、`GET /api/jobs`、`GET /api/jobs/<id>`、`GET /download/<id>/<filename>`。

- [x] **Step 1: Write failing tests**

覆盖：健康检查；缺少上传文件、非 PDF 和超大文件返回 4xx；上传后任务进入队列；fake runner 写出一个白名单结果后状态为 completed；下载结果成功；路径穿越和非白名单下载被拒绝。

- [x] **Step 2: Run tests and verify expected failure**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_server.py -q`

Expected: FAIL because `bankocr.server` does not exist。

- [x] **Step 3: Implement minimal server**

使用线程安全的任务字典和 `ThreadPoolExecutor(max_workers=1)`；multipart 使用标准库 `email` 解析；每个任务写入 `work_dir/jobs/<job_id>/input.pdf`，输出写入 `output/`；runner 默认调用 `bankocr.cli.main` 并传入本地资源路径；HTML 页面使用原生 HTML/JavaScript 轮询 `/api/jobs/<id>`。

- [x] **Step 4: Run focused tests**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_server.py -q`

Expected: PASS。

- [x] **Step 5: Commit**

```text
git add src/bankocr/server.py tests/unit/test_server.py
git commit -m "feat: add local-only BankOCR web service"
```

### Task 2: CLI 入口、依赖和文档

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Create: `docs/使用说明-Linux网页服务.md`
- Test: `tests/unit/test_server.py`

**Interfaces:**
- Console script: `bankocr-server`。
- CLI flags: `--host` default `127.0.0.1`、`--port` default `18081`、`--work-dir`、`--model-dir`、`--model-manifest`、`--template-dir`、`--font-file`、`--dpi`。

- [x] **Step 1: Write failing CLI test**

断言 `bankocr.server.main(["--help"])` 能解析入口；默认绑定地址为 `127.0.0.1`、端口为 `18081`；缺少模型或模板时启动前报清晰错误。

- [x] **Step 2: Run focused test and verify failure**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_server.py -q`

Expected: FAIL because CLI entry point is absent。

- [x] **Step 3: Add console entry and docs**

把 `bankocr-server = "bankocr.server:main"` 加入 `pyproject.toml`；README 和普通用户说明写明 SSH 隧道命令、网页地址、上传流程和结果文件用途；不把服务写成公网开放服务。

- [x] **Step 4: Run tests and compile check**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_server.py -q` and `\.venv\Scripts\python.exe -m compileall -q src tests`

Expected: PASS。

- [x] **Step 5: Commit**

```text
git add pyproject.toml README.md docs/使用说明-Linux网页服务.md tests/unit/test_server.py
git commit -m "docs: add Linux web service entry point"
```

### Task 3: 本地测试样本和 Linux 部署包

**Files:**
- Create: `scripts/build_linux_server_bundle.py`
- Test: `tests/unit/test_linux_server_bundle.py`
- Modify: `packaging/windows/README.md` only if cross-platform artifact list needs correction

**Interfaces:**
- Bundle includes source package, model files, template files, font, lock file, and `deploy/systemd/bankocr-server.service`。
- Bundle must not include user PDFs, SQLite databases, or prior output directories。

- [x] **Step 1: Write bundle test**

断言构建包包含 `src/bankocr/server.py`、模型 manifest、模板 manifest 和 systemd unit，并排除 `.pdf`、`.sqlite3` 和 `work`。

- [x] **Step 2: Implement bundle builder**

生成一个 tar.gz 或目录包，复制已验证资源并生成服务 unit；对每个资源写 SHA-256 manifest。

- [x] **Step 3: Run local service with fake runner and real CLI smoke**

先运行服务单元测试，再用真实 PDF 调用 CLI 产生与现有输出一致的 7 类文件；确认普通 Excel 和 PDF 原样 Excel 均存在。

- [x] **Step 4: Commit**

```text
git add scripts/build_linux_server_bundle.py tests/unit/test_linux_server_bundle.py deploy/systemd/bankocr-server.service
git commit -m "build: add Linux server bundle"
```

### Task 4: VPS 安装、启动和隧道验收

**Files:**
- Remote: `/opt/bankocr-server/`
- Remote: `/etc/systemd/system/bankocr-server.service`
- Local evidence: `work/vps-acceptance-20260826/`

- [x] **Step 1: Copy bundle and verify hashes**

使用 SSH/SCP 将 bundle 复制到 VPS，解压到新的 `/opt/bankocr-server`，不覆盖已有服务。

- [x] **Step 2: Install Python dependencies**

创建 `/opt/bankocr-server/.venv312`，使用 Python 3.12 和 `requirements-linux-server.txt` 安装锁定依赖。RHEL-like distros may also need `mesa-libGL` / `libGL` for OpenCV.

- [x] **Step 3: Install systemd unit**

服务以 `root` 或专用低权限用户运行，工作目录为 `/opt/bankocr-server/data`，绑定 `127.0.0.1:18081`，重启策略为 `on-failure`。

- [x] **Step 4: Verify health and port**

运行 `systemctl is-active bankocr-server`、`ss -lnt | grep 18081` 和 `curl http://127.0.0.1:18081/healthz`；预期服务 active、只监听回环地址、返回 JSON `status=ok`。

- [x] **Step 5: Verify through SSH tunnel**

本地运行 `ssh -L 18081:127.0.0.1:18081 user@192.0.2.10`，浏览器打开 `http://127.0.0.1:18081`，上传无敏感信息的测试 PDF，等待完成，下载普通 Excel 和 `pdf-layout.xlsx`。

- [x] **Step 6: Record limitations and commit deployment notes**

记录模型 fingerprint、服务端口、健康检查、测试输出和未完成的 HTTPS/多用户认证门槛；不要把 PDF、账号、数据库或密钥提交 Git。
