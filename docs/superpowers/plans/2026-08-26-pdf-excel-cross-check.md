# PDF/Excel 对照核验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持原 PDF 页面外观不变的前提下，生成结构化且可追溯的 Excel，并新增一份带交易编号、来源框和风险颜色的核对版 PDF，让人工可以快速把 Excel 每一行与原 PDF 对上。

**Architecture:** 继续保留现有的 `*.searchable.pdf` 作为原貌 PDF，只添加不可见 OCR 文字层；新增独立的 `ComparisonPdfExporter`，从同一份原始 PDF 生成带可视核对标记的副本，不修改输入文件。Excel 不伪装成 PDF 页面，而是增加稳定的 `comparison_id`、来源页、来源坐标、来源块索引和核对状态，并在处理报告中列出核对版 PDF。CLI、任务队列和 GUI 统一暴露新产物。

**Tech Stack:** Python 3.12；PyMuPDF；openpyxl；pytest；现有 `TransactionCandidate`、`FieldValue`、`TextBlock`、`ValidationReport` 和 SQLite 运行结果。

## Global Constraints

- 原始 PDF 永远不覆盖。
- `*.searchable.pdf` 继续保持原页面视觉内容，只添加不可见 OCR 文字层。
- 新的核对版 PDF 是副本，框线和编号只出现在核对版，不出现在原 PDF 和原貌 searchable PDF。
- Excel 中 raw、secondary、suggested、final 四层值继续分开保存。
- 交易编号必须在 Excel 和核对版 PDF 中一致；没有来源坐标的记录必须保留在 Excel，并标记为无法定位，而不是猜测位置。
- 红色表示关键问题/失败，黄色表示待复核或不确定，绿色表示已通过且已确认，灰色表示重复或被拒绝。
- 每次导出都必须把新 PDF 纳入 export manifest 的文件名、大小和 SHA-256。
- 500–1000 页场景不能把整份页面图片嵌入 Excel；核对版 PDF 使用矢量框和文字标记，Excel 只保存来源索引。
- 本轮不自动提交 Git；代码、测试、计划和文档留在当前分支，提交由用户明确要求时再做。

---

### Task 1: 锁定输出模型和来源定位规则

**Files:**
- Create: `outputs/bankocr/docs/superpowers/specs/2026-08-26-pdf-excel-cross-check-design.md`
- Modify: `outputs/bankocr/src/bankocr/export/excel.py`
- Test: `outputs/bankocr/tests/unit/export/test_exporters.py`

**Interfaces:**
- `comparison_id` 使用候选按 `(page_index, row_index)` 排序后的 1-based 序号，格式为 `T0001`、`T0002`；同一候选在 Excel 和核对版 PDF 使用同一编号。
- `source_bbox` 由字段的 `source_block_indices` 对应的 `TextBlock.bbox` 求并集；如果没有块索引，则使用 `FieldValue.source_spans` 的多边形求并集；两者都没有时返回 `None`。
- 无来源坐标的候选仍写入 Excel，`source_location_status` 为 `unlocated`，核对版 PDF 不绘制虚假框。

- [ ] **Step 1: 写失败测试**

在 `test_exporters.py` 增加一个带来源块的候选，调用 Excel 导出后断言 `Transactions` 中存在 `comparison_id`、`source_page`、`source_bbox`、`source_location_status`，并且值为 `T0001`、`1`、`10,10,40,20`、`located`；再增加一个没有来源块索引的候选，断言状态为 `unlocated`。

- [ ] **Step 2: 运行测试确认失败**

运行：`outputs/bankocr/.venv/Scripts/python.exe -m pytest outputs/bankocr/tests/unit/export/test_exporters.py -q`

预期：新增断言失败，因为当前 `Transactions` 没有这些列。

- [ ] **Step 3: 写最小实现**

在 Excel 导出器中增加稳定排序、编号映射和来源定位辅助函数；将以下列加入 `Transactions`：`comparison_id`、`source_page`、`source_bbox`、`source_location_status`。在 `Source Index` 增加同一个 `comparison_id` 和定位状态。保持已有字段及工作表名称不变。

- [ ] **Step 4: 运行测试确认通过**

运行同一个 pytest 命令，预期新增测试和既有 export 测试全部通过。

- [ ] **Step 5: 写设计记录**

在设计文档中写清楚三个文件的用途、编号规则、颜色规则、无坐标时的 fail-closed 行为、输出文件名和人工验收步骤；不写开发者内部过程。

### Task 2: 新增核对版 PDF 导出器

**Files:**
- Create: `outputs/bankocr/src/bankocr/export/comparison_pdf.py`
- Modify: `outputs/bankocr/src/bankocr/export/searchable_pdf.py`
- Test: `outputs/bankocr/tests/unit/export/test_comparison_pdf.py`

**Interfaces:**
- `ComparisonPdfExporter(font_file: str | Path | None = None)`
- `ComparisonPdfExporter.export(source, output, candidates, blocks_by_page, validation_reports=None) -> Path`
- 导出从 `source` 打开并另存为 `output`；`source == output` 时抛出 `ValueError`。
- 输出每页保留原页面，并复用不可见 OCR 文字层；每个有来源坐标的候选绘制一个候选级矩形和 `T####` 标签，不绘制不存在的坐标。

- [ ] **Step 1: 写失败测试**

新建 `test_comparison_pdf.py`：创建一个 200×100 的 PDF、一个来源块和一个候选，运行导出，断言原 PDF 字节未变、核对版 PDF 存在、文本层可提取 `10.00` 和 `T0001`，并断言核对版页面的绘图/文字块数量大于原 PDF。增加同路径覆盖测试，断言抛出 `ValueError`；增加没有来源坐标的候选，断言不会绘制 `T0001` 框。

- [ ] **Step 2: 运行测试确认失败**

运行：`outputs/bankocr/.venv/Scripts/python.exe -m pytest outputs/bankocr/tests/unit/export/test_comparison_pdf.py -q`

预期：导入或类不存在导致失败。

- [ ] **Step 3: 写最小实现**

从 `searchable_pdf.py` 抽取共享的文字层函数，保持 `SearchablePdfExporter` 现有行为不变。新增核对导出器：

1. 用同一文字层把 OCR 结果放回原 PDF；
2. 按候选编号建立候选级来源框；
3. 根据候选状态和页面报告选择绿色、黄色、红色、灰色；
4. 在框旁放置短编号标签，避免长交易 ID 堵塞页面；
5. 使用页面坐标绘制，不进行猜测性缩放；
6. 对没有来源坐标的候选只保留 Excel 记录，不绘制框。

- [ ] **Step 4: 运行测试确认通过**

运行新测试和现有 PDF 导出测试：`outputs/bankocr/.venv/Scripts/python.exe -m pytest outputs/bankocr/tests/unit/export/test_comparison_pdf.py outputs/bankocr/tests/unit/export/test_exporters.py -q`

预期全部通过。

### Task 3: 接入 CLI、任务队列和导出清单

**Files:**
- Modify: `outputs/bankocr/src/bankocr/cli.py`
- Modify: `outputs/bankocr/src/bankocr/task/document_queue.py`
- Modify: `outputs/bankocr/tests/unit/test_cli.py`
- Modify: `outputs/bankocr/tests/unit/task/test_document_queue.py`

**Interfaces:**
- 新文件名：`<stem>.comparison.pdf`。
- CLI、任务队列和人工复核后的 `export_existing` 都生成该文件。
- `summary.json.outputs.comparison_pdf` 保存文件名；`export-manifest.json.outputs.comparison_pdf` 保存 hash/size。

- [ ] **Step 1: 写失败测试**

在 CLI 和任务队列测试中断言新文件存在、summary 包含 `comparison_pdf`，并且 manifest 的输出键集合增加 `comparison_pdf`。将导出器替换为轻量 fake，确认 CLI 把候选、来源块和 validation reports 传给比较导出器。

- [ ] **Step 2: 运行测试确认失败**

运行：`outputs/bankocr/.venv/Scripts/python.exe -m pytest outputs/bankocr/tests/unit/test_cli.py outputs/bankocr/tests/unit/task/test_document_queue.py -q`

预期：新文件和新 manifest 键不存在。

- [ ] **Step 3: 写最小实现**

在 CLI 和 `PdfTaskExecutor._export_artifacts` 中导入 `ComparisonPdfExporter`，把比较 PDF 加入预检输出路径、导出、manifest、summary 和返回的 artifacts 字典；保证人工复核后再次导出也会更新比较 PDF。

- [ ] **Step 4: 运行测试确认通过**

运行上述 CLI/队列测试，预期全部通过；再运行 `outputs/bankocr/.venv/Scripts/python.exe -m pytest outputs/bankocr/tests/unit/export outputs/bankocr/tests/unit/test_cli.py outputs/bankocr/tests/unit/task/test_document_queue.py -q`。

### Task 4: 接入普通员工 GUI

**Files:**
- Modify: `outputs/bankocr/src/bankocr/gui/main_window.py`
- Modify: `outputs/bankocr/tests/unit/gui/test_main_window.py`

**Interfaces:**
- 主界面新增按钮：`打开核对版 PDF`。
- 按钮从任务结果的 `artifacts["comparison_pdf"]` 打开本地文件，不调用命令行或网络。
- 处理说明增加“需要核对时打开核对版 PDF”的用户语言提示。

- [ ] **Step 1: 写失败测试**

在 GUI 测试 fake artifacts 中加入 `comparison_pdf`，断言按钮文字、启用条件、路径选择和本地打开顺序；断言按钮只在任务完成且文件存在时启用。

- [ ] **Step 2: 运行测试确认失败**

运行：`outputs/bankocr/.venv/Scripts/python.exe -m pytest outputs/bankocr/tests/unit/gui/test_main_window.py -q`

预期：窗口没有该按钮或无法打开新 artifact。

- [ ] **Step 3: 写最小实现**

增加按钮、信号连接、结果状态启用逻辑和中文标签映射；不改变已有 Excel、可搜索 PDF、人工复核按钮逻辑。

- [ ] **Step 4: 运行测试确认通过**

运行 GUI 测试，预期全部通过。

### Task 5: 文档、打包入口和真实样本验证

**Files:**
- Modify: `outputs/bankocr/README.md`
- Modify: `outputs/bankocr/docs/使用说明-普通员工.md`
- Modify: `outputs/bankocr/docs/implementation-status.md`
- Modify: `outputs/bankocr/tests/unit/export/test_export_manifest.py`

**Interfaces:**
- 普通员工只需双击 GUI，完成后可以打开 Excel、可搜索 PDF 或核对版 PDF。
- 验收标准：原 PDF SHA-256 不变；新核对 PDF 页数与原 PDF 相同；Excel 中每个有来源的 `comparison_id` 能在核对版 PDF 找到；manifest 含新文件 hash；全量自动化测试通过。

- [ ] **Step 1: 写失败/回归测试**

更新 manifest 测试的输出集合，增加 comparison PDF，并在真实 PDF 验证脚本或测试中检查输入 hash 不变、输出页数一致、核对编号可提取。

- [ ] **Step 2: 运行回归测试确认失败**

先运行对应测试，预期旧断言因输出集合变化而失败。

- [ ] **Step 3: 写文档和实现验证辅助**

更新输出清单、普通员工操作步骤和“核对版 PDF 怎么看”：绿色为已通过、黄色为待复核、红色为关键问题；Excel 的 `comparison_id` 与核对 PDF 标签一致；没有框不代表漏识别，而是来源坐标不足，需查看 `Source Index`。

- [ ] **Step 4: 运行全量验证**

依次运行：

```powershell
Set-Location 'outputs/bankocr'
& '.venv/Scripts/python.exe' -m pytest --basetemp=.pytest-tmp -q
& '.venv/Scripts/python.exe' -m compileall -q src tests scripts
```

然后用 `C:\BankOCR\samples\example-statement.pdf` 生成到一个新的本地验收目录，检查：原文件未修改、`.xlsx`、`.searchable.pdf`、`.comparison.pdf`、`.review.xlsx`、`summary.json`、`export-manifest.json` 都存在；打开核对版 PDF 做第一页视觉检查；打开 Excel 检查 `T0001` 和来源列。

- [ ] **Step 5: 完成前复核**

用 `git diff --check`、`git status --short` 和全量测试输出核对没有空白错误、未跟踪敏感业务数据或未声明的输出变更；不自动提交 Git。

---

## 计划自检

- **规格覆盖：** 只新增导出和核对体验，不改变 OCR、Parser、Validation、SQLite、原 PDF 保护和离线约束；已有数据链路通过 `TransactionCandidate`、`FieldValue`、`TextBlock`、`ValidationReport` 复用。
- **无占位符：** 每个任务给出实际文件、接口、测试命令、预期结果和处理规则。
- **类型一致：** `ComparisonPdfExporter.export` 在 Task 2 定义，在 CLI 和任务队列中按同一参数调用；`comparison_pdf` 在所有输出字典中使用同一键名。
- **已知边界：** Excel 不承诺逐像素复刻 PDF；核对版 PDF 负责视觉一致性，Excel 负责结构化筛选和证据索引。
