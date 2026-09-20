# BankOCR 结果整理与一键下载 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Linux 网页服务的处理结果按用途整齐展示，并提供不包含原始 PDF 的一键 ZIP 下载。

**Architecture:** 在现有 `bankocr.server` 中增加受任务输出清单约束的按需 ZIP 接口，使用临时文件生成压缩包并在响应结束后清理。网页继续使用现有内嵌 HTML/CSS/JavaScript，但把结果卡片拆成用途分组，保留所有原有单文件下载链接。

**Tech Stack:** Python 3.12；标准库 `zipfile`、`tempfile`、`http.server`；原生 HTML/CSS/JavaScript；pytest；现有 Nginx HTTPS 入口。

**Spec:** `docs/superpowers/specs/2026-08-26-result-download-design.md`

## Global Constraints

- 压缩包只包含任务 `output_files` 中登记的结果文件，不包含原始 PDF、SQLite、临时文件或其他任务文件。
- ZIP 只允许已完成任务下载；处理中返回 409；不存在的任务返回 404。
- ZIP 内成员只使用文件名，不允许目录穿越。
- 保留原有单文件下载接口和每 2 秒自动刷新任务状态的行为。
- 不改变 OCR、解析、校验、导出和 Windows GUI。
- Nginx HTTPS、Basic Auth、后端 `127.0.0.1:18081`，以及其他本机已有服务保持不变。

---

### Task 1: 增加受限的 ZIP 下载接口

**Files:**
- Modify: `src/bankocr/server.py`（导入、`ServerRuntime`、GET 路由和响应辅助方法）
- Test: `tests/unit/test_server.py`（ZIP 内容、状态码和安全边界）

**Interfaces:**
- Produces `ServerRuntime.archive_members(job_id: str) -> tuple[str, tuple[Path, ...]]`，返回原始文件名和已验证的结果文件路径。
- Produces `GET /download/<job_id>/all.zip`，返回 `application/zip`。

- [ ] **Step 1: Add failing tests**

在 `tests/unit/test_server.py` 增加 `io` 和 `zipfile` 导入，并加入以下测试。测试使用现有 `_config`、`_multipart`、`_request` 辅助函数，fake runner 只写入测试内容：

```python
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
        status, _, uploaded = _request(server.server_address[1], "POST", "/upload", body, headers)
        assert status == 202
        job_id = json.loads(uploaded)["id"]

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, _, payload = _request(
                server.server_address[1], "GET", f"/api/jobs/{job_id}"
            )
            current = json.loads(payload)
            if current["status"] == "completed":
                break
            time.sleep(0.02)
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
    finally:
        server.shutdown()
        server.server_close()
        runtime.shutdown()
        thread.join(timeout=2)
```

再加入一个阻塞 runner 测试：runner 用 `threading.Event` 等待，上传完成并确认 runner 已启动后请求 `/download/<job_id>/all.zip`，断言返回 409；释放事件后任务完成。请求一个不存在的 12 位十六进制任务编号，断言返回 404。

- [ ] **Step 2: Run the new tests and verify the expected failure**

Run:

```text
.\.venv\Scripts\python.exe -m pytest tests/unit/test_server.py -k "zip or archive" -q
```

Expected: FAIL because `/download/<job_id>/all.zip` is not implemented yet and currently falls through to the ordinary file download path.

- [ ] **Step 3: Implement the minimal archive boundary**

在 `src/bankocr/server.py` 中：

1. 导入 `tempfile` 和 `zipfile`。
2. 在 `ServerRuntime` 增加 `archive_members`：锁内读取任务；任务不存在抛出 `KeyError`；状态不是 `completed` 抛出 `RuntimeError("任务尚未完成")`；逐个检查 `PurePosixPath(filename).name == filename`、路径父目录等于任务 output 根目录且文件存在；任何结果文件缺失抛出 `FileNotFoundError`；返回原始文件名和路径元组。
3. 在普通 `/download/<job_id>/<filename>` 路由之前匹配 `/download/<job_id>/all.zip`。
4. 新增 `_send_archive(job_id)`：调用 `archive_members`，用 `tempfile.TemporaryFile()` 和 `zipfile.ZipFile(..., ZIP_DEFLATED)` 写入所有成员，`arcname=path.name`；关闭 ZIP 后计算长度、回到文件开头并分块发送；响应头使用 `Content-Type: application/zip`、`Content-Length` 和以原始文件名 stem 生成的安全 ZIP 文件名。发送结束后关闭临时文件。
5. 路由异常映射为：`KeyError -> 404`，`RuntimeError -> 409`，`FileNotFoundError/ValueError/OSError -> 500`；错误响应不泄露服务器绝对路径。

- [ ] **Step 4: Run the focused tests and then the full suite**

Run:

```text
.\.venv\Scripts\python.exe -m pytest tests/unit/test_server.py -q
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp -q
```

Expected: focused server tests and the full suite pass with zero failures.

- [ ] **Step 5: Commit the archive endpoint**

```text
git add src/bankocr/server.py tests/unit/test_server.py
git commit -m "feat: add all-results zip download"
```

### Task 2: 整理网页结果卡片

**Files:**
- Modify: `src/bankocr/server.py`（`_INDEX_HTML` 的 CSS、结果卡片 DOM 和渲染 JavaScript）
- Test: `tests/unit/test_server.py`（网页静态内容断言）

**Interfaces:**
- Consumes `job.output_files` 和 `job.status`，不改变 API JSON 结构。
- Uses `GET /download/<job_id>/all.zip` for the primary ZIP button.

- [ ] **Step 1: Add failing UI assertions**

扩展现有 `test_server_page_renders_job_fields_as_text_nodes`，断言首页 HTML 包含以下静态文案和行为标识：

```python
assert "下载全部结果 ZIP" in html
assert "直接使用" in html
assert "和 PDF 对照" in html
assert "人工复核" in html
assert "处理记录" in html
assert "/all.zip" in html
```

Run:

```text
.\.venv\Scripts\python.exe -m pytest tests/unit/test_server.py::test_server_page_renders_job_fields_as_text_nodes -q
```

Expected: FAIL because the current page renders one没有分组的链接段落 and no ZIP link.

- [ ] **Step 2: Implement the grouped result view**

在 `_INDEX_HTML` 中保持现有安全的 `document.createTextNode` 写入方式，增加以下固定分组和后缀识别顺序：

```javascript
const resultGroups = [
  { key: 'use', title: '直接使用', hint: '用于整理、搜索和统计', files: [] },
  { key: 'compare', title: '和 PDF 对照', hint: '用于逐页查看原文位置', files: [] },
  { key: 'review', title: '人工复核', hint: '只列出需要人工确认的项目', files: [] },
  { key: 'audit', title: '处理记录', hint: '保存处理过程和文件校验信息', files: [] },
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
```

完成任务的卡片顶部放置 `<a class="download-all">下载全部结果 ZIP</a>`，链接为 `/download/` + job id + `/all.zip`；非 `completed` 状态不渲染该按钮。每个分组只在有文件时显示，链接显示中文标签，实际文件名写入 `title` 属性并以文本节点安全渲染。卡片头部使用 flex 布局，结果链接使用 grid/flex 换行，长文件名不作为主显示文本，从而避免截图中的横向挤压。

CSS 只使用明确的过渡属性，不使用 `transition: all`；状态使用颜色和文字双重表达；主 ZIP 按钮使用较高对比度和至少 40px 高度，窄屏时卡片头部和链接自动换行。

- [ ] **Step 3: Run the UI test and full suite**

```text
.\.venv\Scripts\python.exe -m pytest tests/unit/test_server.py -q
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp -q
```

Expected: all server tests and the full suite pass.

- [ ] **Step 4: Commit the grouped UI**

```text
git add src/bankocr/server.py tests/unit/test_server.py
git commit -m "feat: organize web result downloads"
```

### Task 3: 文档、VPS 部署和公网验收

**Files:**
- Modify: `docs/使用说明-Linux网页服务.md`（增加 ZIP 使用说明）
- Modify: `README.md`（补充网页结果分组和 ZIP 功能）

**Interfaces:**
- Deploys the tested `src/bankocr/server.py` to `/opt/bankocr-server/src/bankocr/server.py`.
- Does not modify Nginx, ports, model files, or other local services.

- [ ] **Step 1: Update user documentation**

在 Linux 网页服务文档的“输出文件”前增加：处理完成后优先点击“下载全部结果 ZIP”；ZIP 只包含结果文件，不包含原始 PDF。说明单个链接仍可分别下载，并解释 `pdf-layout.xlsx` 和 `comparison.pdf` 的用途。

- [ ] **Step 2: Run local release checks**

```text
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp -q
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
git diff --check
```

Expected: 261+ tests pass, compileall succeeds, and `git diff --check` has no errors.

- [ ] **Step 3: Upload only the changed server source and restart the service**

先确认 VPS 当前服务为 `bankocr-server.service`、后端监听 `127.0.0.1:18081`；再用已有 SSH 密钥上传 `src/bankocr/server.py` 到 `/opt/bankocr-server/src/bankocr/server.py`，保留远程备份，执行 `systemctl restart bankocr-server`，等待 `GET http://127.0.0.1:18081/healthz` 返回 200。若服务未恢复，立即用备份还原并停止后续步骤。

- [ ] **Step 4: Run a no-sensitive-data public smoke test**

使用本地生成的无敏感信息 PDF，通过 `https://ocr.example.com` 登录后上传；轮询任务直到 `completed`；下载 `/download/<job_id>/all.zip`，验证 HTTP 200、压缩包可打开、包含全部结果文件且不包含原始 PDF。测试结束后清理该测试任务并确认任务列表恢复干净。

- [ ] **Step 5: Verify production boundaries**

确认：公网未登录返回 401；带登录的首页和 `/healthz` 返回 200；`nginx -t` 成功；`bankocr-server.service` 为 active；`18081` 仍只监听 `127.0.0.1`；其他本机已有服务保持不变；HTTPS 证书和 Nginx 配置未被改动。

- [ ] **Step 6: Commit and push the documentation and implementation**

```text
git add README.md docs/使用说明-Linux网页服务.md
git commit -m "docs: explain grouped results and zip download"
git push origin main
```

最后运行 `git status --short` 和 `git ls-remote origin refs/heads/main`，确认工作区干净且远程 main 与本地 HEAD 一致。

