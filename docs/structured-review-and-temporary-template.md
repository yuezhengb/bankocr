# BankOCR 结构化复核与 Temporary Template 使用说明

## 1. 本次已补齐的能力

### 结构化人工复核

复核窗口现在除了字段改值、接受、拒绝，还支持：

- **Move up / Move down**：只改变同页展示/导出顺序，不改 OCR 来源的 `page_index + row_index`。
- **Merge with next**：合并两行，保留两行所有 `source_block_indices` 和 `source_spans`；冲突值会拼接并重新进入待复核状态。
- **Split fields**：把选中的字段拆成新行；原行和新行都必须重新确认。
- **Add missing row**：补录缺失行，字段输入仍保留在最终层之外的人工复核链路中。
- **Mark duplicate**：保留重复行、关联原行，不静默删除；Excel 中显示 `duplicate` 和 `duplicate_of`，重复行不生成业务 `transaction_id`。

每次结构操作都写入 `project.sqlite3` 的 `review_events`，包括操作前后页面候选快照、操作者和 UTC 时间。来源 PDF 永远不被修改。

### Temporary Template

未知版式无法可靠映射时仍然停在 `PAGE_REVIEW`，不会猜测列。复核员确认列名和相对页面边界后，可以保存一个只属于当前 Run 的 Temporary Template：

- 不写入 `templates/known`；
- 不改变正式模板包 manifest；
- 只对保存它的 `run_id` 生效；
- 通过 Run 的重跑路径复用；
- 列边界重叠、required field 不存在等情况直接拒绝保存。

## 2. 最短使用流程

以下示例使用用户当前的仓库和 PDF。请把路径替换成自己的实际目录；PowerShell 不要把 `$Input` 当作 PDF 路径变量，使用 `$PdfPath`。

### 第一步：处理 PDF 并保存项目数据库

```powershell
$Repo = "C:\BankOCR"
$Release = "$Repo\work\release-candidate-20260809-v12"
$PdfPath = "C:\BankOCR\samples\example-statement.pdf"
$Accept = "$Repo\work\manual-acceptance-$(Get-Date -Format yyyyMMdd-HHmmss)"

New-Item -ItemType Directory -Path "$Accept\output" -Force | Out-Null

& "$Release\bankocr-process.exe" "$PdfPath" `
  --output-dir "$Accept\output" `
  --project-db "$Accept\project.sqlite3" `
  --dpi 200 `
  --model-dir "$Release\models" `
  --model-manifest "$Release\models\manifest.json" `
  --template-dir "$Release\templates\known" `
  --font-file "C:\Windows\Fonts\msyh.ttc"
```

查看：

```powershell
Get-Content "$Accept\output\example-statement.summary.json" | ConvertFrom-Json
```

其中 `run_id` 是后续复核和恢复使用的 Run 编号。

### 第二步：打开人工复核

如果已经构建了带 GUI 的 release：

```powershell
& "$Release\bankocr-review.exe" `
  --project-db "$Accept\project.sqlite3" `
  --run-id 1
```

在窗口中选中交易行即可执行结构操作。遇到 `PAGE_REVIEW` 页面时，点击“确认 Temporary Template”，在 OCR 块证据旁明确填写表头、字段和列边界，保存后当前 Run 的待处理页面会重新排队。操作完成后点保存；系统会重新验证并重新生成导出文件。主 GUI 中点击“开始”即可执行重新排队的 Run；独立 `bankocr-review.exe` 保存后再用下面的 `--resume-run` 命令重跑。

如果当前 release 还没有包含最新 GUI，使用源码环境：

```powershell
Set-Location $Repo
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "offscreen"   # 仅在无桌面测试时使用；正常 GUI 可删除
& ".\.venv\Scripts\python.exe" -m bankocr.review_cli `
  --project-db "$Accept\project.sqlite3" `
  --run-id 1
```

### 第三步：确认未知版式的 Temporary Template

以 0 开始计页码。列比例是 0 到 1 的页面宽度比例，格式为 `字段名:左边界:右边界`。

源码环境命令：

```powershell
Set-Location $Repo
$env:PYTHONPATH = "src"
& ".\.venv\Scripts\python.exe" -m bankocr.template_cli `
  --project-db "$Accept\project.sqlite3" `
  --run-id 1 `
  --source-page 0 `
  --headers "日期,金额,余额" `
  --columns "accounting_date:0:0.30;transaction_amount:0.30:0.70;balance:0.70:1" `
  --required-fields "accounting_date,balance" `
  --reviewer "reviewer-a"
```

该命令会保存模板，并把当前 Run 的 `needs_review` 页面重新排入 pending。随后用原来的模型、模板和字体参数恢复：

```powershell
& "$Release\bankocr-process.exe" "$PdfPath" `
  --output-dir "$Accept\output" `
  --project-db "$Accept\project.sqlite3" `
  --resume-run 1 `
  --dpi 200 `
  --model-dir "$Release\models" `
  --model-manifest "$Release\models\manifest.json" `
  --template-dir "$Release\templates\known" `
  --font-file "C:\Windows\Fonts\msyh.ttc"
```

如果没有使用 `bankocr-template` 命令，而是手动把页面置为 `needs_review`，可在恢复时显式加：

```powershell
--reprocess-review-pages
```

## 3. output 目录中的文件怎么看

| 文件 | 用途 |
|---|---|
| `*.xlsx` | 主结果；`Transactions` 是业务表，`Processing Report` 是统计，`Source Index` 是来源证据。 |
| `*.pdf-layout.xlsx` | PDF 原样图片版；每个 PDF 页面一个工作表，另有“核对索引”用于跳转；不能筛选图片内文字。 |
| `*.review.xlsx` | 仍需要人工处理的校验问题和页面问题。 |
| `*.searchable.pdf` | 原始页面加不可见文字层；原始 PDF 不覆盖。 |
| `*.comparison.pdf` | 原始页面加交易来源框和 `T0001` 等核对编号；原始 PDF 不覆盖。 |
| `*.export-manifest.json` | 本次导出的源文件 SHA-256、输出文件 hash/size、Run 编号和 unresolved 数量。 |
| `*.summary.json` | 页数、页面状态、解析状态和验证状态。 |
| `project.sqlite3` | Run、页面 checkpoint、OCR 块、候选、Temporary Template 和人工审计事件。 |

验收时至少检查：

```powershell
$manifest = Get-Content "$Accept\output\example-statement.export-manifest.json" | ConvertFrom-Json
$manifest.unresolved_count
Get-Content "$Accept\output\example-statement.summary.json" | ConvertFrom-Json
```

只有 `unresolved_count` 为 0、`summary.run_status` 为 `completed`，并且人工抽查 Excel 与源 PDF 一致时，才可把这一次结果作为业务交付候选。

## 4. 为什么说方案更安全

1. **不把不确定结果伪装成成功**：未知版式和关键校验无法确认时进入 `PAGE_REVIEW`。
2. **证据链完整**：raw OCR、secondary OCR、suggested、final 分层保存，字段保留原始块索引和 PDF 坐标。
3. **人工修改可追溯**：字段和结构复核均写入 SQLite；合并、拆分、补录和重复标记不会静默删除来源。
4. **数据不出本机**：模型、模板、OCR 和导出均从本地路径读取，运行时不需要下载或上传。
5. **输入不覆盖**：输出单独写入 output 目录，并用 manifest hash 校验产物。
6. **Run 可复现**：模型、模板、parser、rules 和源文件 hash 固定；Temporary Template 也按 Run 隔离。

这证明的是代码层和当前开发机上的可复核安全机制，不等于已经完成正式发布安全认证。

## 5. 仍必须由外部证据完成的门槛

以下项目不能在当前一台开发机上代替完成：

- 500–1000 页、按 statement/account/layout 隔离的 Locked Holdout；
- 独立第二人复核 truth、Silent Critical Error 统计；
- 全新 Windows x64 快照/虚拟机的断网安装、运行、升级、回滚、卸载；
- Authenticode 签名、SmartScreen/Defender 扫描与分发结果；
- CJK 字体再分发授权、第三方许可证和 SBOM 归档。

因此当前状态仍是 **release candidate，不是正式 V1 release**。
