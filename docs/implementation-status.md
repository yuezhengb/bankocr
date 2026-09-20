# BankOCR V1 实施状态

**状态日期：** 2026-08-26
**基线：** `docs/specifications/BankOCR_V1_Design_Specification_v1.1.docx`

## 当前结论

当前仓库是 **V1 engineering-complete / release-candidate**，不是正式 V1 release。核心 OCR、解析、校验、SQLite checkpoint、Review、导出和离线打包路径已经存在并有自动化测试；v1.1 审计发现的 provenance、Native Text Quality Gate、四态校验和 Export Manifest 缺口已修复到代码中。

正式发布仍被外部证据阻塞：500–1000 页 release Golden Set、独立 truth 复核、全新断网 Windows x64 验收、Authenticode/SmartScreen/Defender、CJK 字体授权以及第三方 license/SBOM 审查。

详细逐项矩阵见 [`docs/v1.1-spec-implementation-audit.md`](v1.1-spec-implementation-audit.md)，正式门槛见 [`docs/v1-release-gate.md`](v1-release-gate.md)。

## 2026-08-09 本机 GUI release candidate 证据

- 自动化验证：`pytest --basetemp=.pytest-tmp -q` 为 **240 passed in 3.31s**；`compileall -q src tests scripts` 退出码为 0；`pip check` 输出 `No broken requirements found.`
- Windows 构建：通过 `scripts\build_windows.ps1 -Backend pyinstaller -OutputRoot work\windows-build-v13` 生成并检查四个 EXE：`bankocr-process.exe`、`bankocr-template.exe`、`bankocr-review.exe`、`bankocr-gui.exe`。
- 离线候选包：新建 `work\release-candidate-20260809-gui`；输入模型来自已验证的 `work\release-candidate-20260809-v12\models`，而非仓库根目录仅含 README 的 `models`。
- 离线核验：`verify_offline_release.py` 通过；模型 fingerprint 为 `787666f230518edd1dcdd389828d45faa7c4f45de48490f08d0eed2e11d3dd38`。
- 本机可执行验收：新 `bankocr-process.exe` 成功处理 `C:\BankOCR\samples\example-statement.pdf` 到 `work\local-acceptance-20260809-process`。该目录包含 Excel、Review Excel、searchable PDF、summary 和 export manifest；summary 报告 2 页，export manifest 的 `unresolved_count` 为 0。
- GUI 启动探针：无参数启动新 `bankocr-gui.exe` 后进程保持存活超过 5 秒，随后已结束探针进程。该证据仅说明本机无参数启动成功，**不构成手工 GUI 流程、文件选择、处理或 Review 动作验收通过**。

Task 5 的摘要、资产 hash 与验收边界见 [Task 5 报告](../.superpowers/sdd/task-5-report.md)；实际重跑产生的命令元数据、stdout/stderr 与启动探针记录见 [`docs/verification/2026-08-09-zero-config-gui/`](verification/2026-08-09-zero-config-gui/)。

## 2026-08-26 PDF 原样图片版 Excel 证据

- 新增 `*.pdf-layout.xlsx`：每个 PDF 页面一个工作表，另有“核对索引”页和页码跳转链接；普通 `*.xlsx` 保持为搜索、统计和整理用途。
- 自动化验证：全量 pytest **256 passed**；`compileall` 退出码为 0；`pip check` 输出 `No broken requirements found.`。
- 真实样本验证：`C:\BankOCR\samples\example-statement.pdf`（2 页）成功生成布局 Excel，工作簿为 3 个工作表，每个 PDF 页面各嵌入 1 张原页图片，原 PDF 页数和 SHA-256 未改变。
- 新离线候选包：`work\release-candidate-20260826-pdf-layout`；离线模型核验通过；打包版 `bankocr-process.exe` 生成了普通 Excel、PDF 原样 Excel、Review Excel、可搜索 PDF、核对版 PDF、summary 和 export manifest。
- GUI 启动探针：新打包版 `bankocr-gui.exe` 无参数启动后保持运行超过 5 秒；该证据不替代人工点击流程验收。

## 已有代码证据

| 模块 | 当前状态 | 证据 |
|---|---|---|
| PDF 分类、坐标和流式处理 | 已实现 | `src/bankocr/pdf/`、`src/bankocr/image/`、`src/bankocr/pipeline/processor.py` |
| CPU-first RapidOCR / 本地模型 | 已实现 | `src/bankocr/ocr/`、模型 manifest 和 hash 校验 |
| Known Template / Positional / Generic | 部分实现 | 已知布局可运行；未知布局无法可靠映射时返回 `PAGE_REVIEW` |
| 稳定 TextBlock ID / source spans | 已实现 | `domain/text_block.py`、SQLite schema v6、Source Index |
| Native Text Quality Gate | 部分实现 | 异常字符、bbox、稀疏/异常高度检查和 OCR fallback 已有；关键字段覆盖率/区域级策略待补 |
| Decimal 校验 / Secondary OCR | 部分实现 | `validation/`、`ocr/secondary.py`；正式 holdout 尚未完成 |
| Excel / PDF 原样 Excel / Review Excel / searchable PDF / comparison PDF | 部分实现 | 结构化 Excel、逐页原 PDF 图片 Excel、原貌 searchable PDF 和带来源框/编号的 comparison PDF 可生成；每次导出附 `*.export-manifest.json`；正式 holdout 和新机验收仍待完成 |
| SQLite project/run/resume | 已实现（核心） | schema v6、source SHA、page checkpoint、结构复核、Temporary Template 和 review audit |
| PySide6 主窗口 | 已实现（核心） | 任务队列、字段/结构复核和 Generic Temporary Template 映射向导已有；新机验收仍待完成 |
| Windows 打包 | 工程完成 | PyInstaller fallback/离线验证路径已有；正式签名和新机验收待完成 |

## 当前可引用的 PoC 证据

已有 4 页、92 条 truth row 的样本 A/B 结果：日期、金额、余额、行关联均为 100%，Review 0%，Silent Critical 0%，峰值 RSS 约 814 MB。这个结果只证明当前两个已知布局，不外推到任意银行或任意扫描质量。

## 明确未完成项

1. Temporary Template 自动转正式模板；
2. 全新 Windows、签名、SmartScreen/Defender、字体授权、500–1000 页 holdout 和独立复核等外部证据；
3. anchor/table-local 模板坐标，当前仍以 page-relative ratio 为主；
4. 500–1000 页分层 benchmark 与独立第二人 truth 复核；
5. searchable PDF viewer benchmark 和 OCRmyPDF fallback 验证；
6. 全新断网 Windows 安装/卸载、正式签名、SmartScreen/Defender、字体授权和 license 审查。

## 运行与测试

```powershell
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp -q
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
.\.venv\Scripts\python.exe -m pip check
```

在以上未完成项归档前，不创建正式 `v1.0.0` tag。
