# PDF 原样图片版 Excel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有结构化输出的前提下，生成可逐页视觉对照原始 PDF 的 `pdf-layout.xlsx`，并让 CLI、桌面队列、清单和结果按钮保持一致。

**Architecture:** 新增独立的 `PdfLayoutExcelExporter`，用 PyMuPDF 按固定 DPI 渲染原始 PDF 页面，再用 openpyxl 将每页图片嵌入独立工作表；索引页只保存可定位的结构化信息和页面超链接。CLI 与 `PdfTaskExecutor` 共用该导出器，避免两套导出逻辑产生不同文件。

**Tech Stack:** Python 3.12；PyMuPDF；openpyxl；Pillow（openpyxl 图片支持）；pytest；PySide6（GUI 测试）。

## Global Constraints

- 原始 PDF 永不覆盖。
- `pdf-layout.xlsx` 页面必须与 PDF 页数一一对应，包括空白页。
- 页面图片不叠加 OCR、标记或二次绘制。
- 普通 `.xlsx` 继续负责搜索、统计和整理。
- 150 DPI PNG 作为默认图片格式，保证小字和符号清晰。
- 资源文件只保存在临时目录，导出结束后清理。
- CLI、桌面任务队列和人工复核后的重新导出都必须生成同名布局文件。

---

### Task 1: PDF 页面图片版 Excel 导出器

**Files:**
- Create: `src/bankocr/export/pdf_layout.py`
- Test: `tests/unit/export/test_pdf_layout.py`
- Modify: `src/bankocr/export/__init__.py` only if a public export is needed

**Interfaces:**
- Consumes: `source: str | Path`、`output: str | Path`、`candidates: Sequence[TransactionCandidate]`。
- Produces: `PdfLayoutExcelExporter(dpi: int = 150).export(source, output, candidates) -> Path`。

- [ ] **Step 1: Write the failing tests**

测试必须创建一个两页 PDF和两个候选交易，调用真实导出器，检查页签、图片数量、页码链接和原 PDF 页宽高比。

```python
def test_pdf_layout_excel_contains_one_image_sheet_per_pdf_page_and_index(tmp_path: Path) -> None:
    source = _make_two_page_pdf(tmp_path / "statement.pdf")
    output = tmp_path / "statement.pdf-layout.xlsx"
    candidates = (_candidate(page_index=0, row_index=1), _candidate(page_index=1, row_index=2))

    PdfLayoutExcelExporter().export(source, output, candidates)

    workbook = load_workbook(output)
    assert workbook.sheetnames == ["核对索引", "第001页", "第002页"]
    assert len(workbook["第001页"]._images) == 1
    assert len(workbook["第002页"]._images) == 1
    index = workbook["核对索引"]
    headers = [cell.value for cell in index[2]]
    assert "comparison_id" in headers
    assert "PDF页" in headers
    assert index[2][headers.index("PDF页")].hyperlink.target == "#'第001页'!A1"

    document = pymupdf.open(source)
    ratio = document[0].rect.width / document[0].rect.height
    document.close()
    image = workbook["第001页"]._images[0]
    assert image.width / image.height == pytest.approx(ratio, rel=0.02)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/export/test_pdf_layout.py -q`

Expected: FAIL because `bankocr.export.pdf_layout` and `PdfLayoutExcelExporter` do not exist.

- [ ] **Step 3: Implement the exporter**

实现以下行为：打开 PDF；创建 `核对索引`；为每个页面创建 `第{page_index + 1:03d}页` 工作表；用 `page.get_pixmap(dpi=150, alpha=False)` 写入临时 PNG；按 PDF 页面宽高比设置图片尺寸并放到 `A1`；设置打印方向和页面适配；用 `comparison_ids(sorted(candidates, key=candidate_sort_key))` 为候选生成稳定编号；索引行写入页码、行号、编号、状态和超链接；保存工作簿；在 `TemporaryDirectory` 退出时清理 PNG。

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/unit/export/test_pdf_layout.py -q`

Expected: PASS。

- [ ] **Step 5: Commit**

```text
git add src/bankocr/export/pdf_layout.py tests/unit/export/test_pdf_layout.py
git commit -m "feat: add PDF layout Excel exporter"
```

### Task 2: 接入任务队列、CLI、摘要和导出清单

**Files:**
- Modify: `src/bankocr/task/document_queue.py`
- Modify: `src/bankocr/cli.py`
- Modify: `tests/unit/task/test_document_queue.py`
- Modify: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `PdfLayoutExcelExporter.export`。
- Produces: artifact key `pdf_layout_excel`、文件名 `<stem>.pdf-layout.xlsx`，并出现在 `outputs` 和摘要 JSON。

- [ ] **Step 1: Write failing integration assertions**

在任务队列和 CLI 测试中断言新文件存在，`summary["outputs"]["pdf_layout_excel"]` 正确，`ExportManifest` 的 output key 也含 `pdf_layout_excel`。

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest tests/unit/task/test_document_queue.py tests/unit/test_cli.py -q`

Expected: FAIL because the new artifact is absent。

- [ ] **Step 3: Implement the shared export call**

在两个导出路径导入 `PdfLayoutExcelExporter`，调用同一文件名；把路径加入 `_output_paths`，加入导出清单、summary 和返回的 artifacts 字典。旧输出保持不变。

- [ ] **Step 4: Run focused tests and existing export tests**

Run: `python -m pytest tests/unit/task/test_document_queue.py tests/unit/test_cli.py tests/unit/export -q`

Expected: PASS。

- [ ] **Step 5: Commit**

```text
git add src/bankocr/task/document_queue.py src/bankocr/cli.py tests/unit/task/test_document_queue.py tests/unit/test_cli.py
git commit -m "feat: include PDF layout Excel in exports"
```

### Task 3: 接入桌面端结果按钮

**Files:**
- Modify: `src/bankocr/gui/main_window.py`
- Modify: `tests/unit/gui/test_main_window.py`

**Interfaces:**
- Consumes: task result artifact key `pdf_layout_excel`。
- Produces: 用户可点击的“打开 PDF 原样 Excel”按钮，打开 `<stem>.pdf-layout.xlsx`。

- [ ] **Step 1: Write the failing GUI assertions**

给测试夹具增加布局文件和 artifact key，断言按钮文本、完成后的启用状态、`_selected_artifact_path("pdf_layout_excel")` 和打开顺序。

- [ ] **Step 2: Run the focused GUI test to verify it fails**

Run: `python -m pytest tests/unit/gui/test_main_window.py::test_main_window_exposes_completed_outputs_and_result_actions -q`

Expected: FAIL because the button and artifact mapping do not exist。

- [ ] **Step 3: Implement the button and action mapping**

新增按钮，连接 `_open_artifact("pdf_layout_excel")`，在运行中禁用、完成后根据文件存在启用，并在标签映射中显示“PDF 原样 Excel”。保持普通“打开 Excel”按钮的行为不变。

- [ ] **Step 4: Run all GUI tests**

Run: `python -m pytest tests/unit/gui -q`

Expected: PASS。

- [ ] **Step 5: Commit**

```text
git add src/bankocr/gui/main_window.py tests/unit/gui/test_main_window.py
git commit -m "feat: add PDF layout Excel GUI action"
```

### Task 4: 文档、构建和真实样本验证

**Files:**
- Modify: `README.md` or the existing user guide under `docs/` with the new output explanation
- Modify: `packaging/windows/README.md` if artifact list is documented
- Test: `tests/unit/export/test_pdf_layout.py` and the full test suite

**Interfaces:**
- Consumes: all completed exporters and GUI artifact mapping。
- Produces: 用户能理解的输出说明、可复现的验证记录。

- [ ] **Step 1: Update user-facing documentation**

明确写出：普通 `.xlsx` 用于搜索统计；`pdf-layout.xlsx` 用于逐页视觉对照；`review.xlsx` 只列待处理问题；JSON 是审计信息，通常不需要打开或修改。

- [ ] **Step 2: Run the full automated suite**

Run: `python -m pytest -q`

Expected: all tests pass。

- [ ] **Step 3: Export the supplied sample PDF**

使用当前离线运行环境对一个真实样本导出，检查输出目录同时有普通 `.xlsx` 和 `.pdf-layout.xlsx`，并用 openpyxl 检查工作表数量等于 PDF 页数加一。

- [ ] **Step 4: Inspect a rendered workbook page**

用 Excel 或 LibreOffice 打开 `pdf-layout.xlsx`，检查第一页图片没有被裁切、比例没有变形、空白页仍存在，索引页链接能跳到对应页签。

- [ ] **Step 5: Commit and report evidence**

```text
git add README.md packaging/windows/README.md docs/superpowers/specs docs/superpowers/plans
git commit -m "docs: document PDF layout Excel output"
git status --short --branch
```

验收报告必须列出测试命令、通过数量、真实样本输出路径和未完成的发布级验证项目。
