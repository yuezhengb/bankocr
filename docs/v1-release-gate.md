# BankOCR V1 Release Gate

**状态日期：** 2026-08-09
**当前判定：** **NOT PASSED — release candidate only**

## 状态定义

- **已实现**：代码、测试和当前环境有直接证据。
- **工程完成**：已具备实现路径，但正式发布仍需要更大数据集或外部环境证据。
- **未通过**：不能创建正式 V1 tag 或对外宣称达到发布门槛。

## 2026-08-09 本机 release candidate 证据（不关闭外部 Gate）

- 新建 `work\windows-build-v13`，检查到 PyInstaller 的四个 EXE：process、template、review、gui。
- 新建 `work\release-candidate-20260809-gui`；离线模型/资产核验通过，模型 fingerprint 为 `787666f230518edd1dcdd389828d45faa7c4f45de48490f08d0eed2e11d3dd38`。
- `bankocr-process.exe` 在本机成功处理指定 2 页 PDF，生成 Excel、Review Excel、searchable PDF、summary 和 export manifest；未解决项计数为 0。
- `bankocr-gui.exe` 的无参数启动探针中进程保持存活超过 5 秒；未进行人工文件选择、处理、Review 操作或新机验收。
- 对应的实际命令元数据、开始/结束时间、exit code、stdout/stderr 与机器可读启动探针均归档在 [`docs/verification/2026-08-09-zero-config-gui/`](verification/2026-08-09-zero-config-gui/)。

这些证据只补充 G1 的本机自动化命令以及 G7/G9 的部分本机构建/可执行检查；它们**不**通过 G2–G10，也不使该候选包成为正式 V1。

## 门槛矩阵

| Gate | 目标 | 当前状态 | 通过条件 |
|---|---|---|---|
| G1 基础自动化 | 单元、集成、compileall、pip check、diff check | 工程完成 | 当前分支全部命令 fresh pass，并保存日志；本机 2026-08-09 证据为 240 passed、compileall 退出 0、pip check 无损坏依赖 |
| G2 Known Template | 关键字段、行关联、余额连续性、Silent Critical Error | 已知样本通过 | 在扩展数据集上满足发布阈值 |
| G3 Native/Hybrid | Quality Gate、fallback、去重、坐标 | 部分完成 | 补齐关键字段覆盖率、区域 fallback 和 viewer 证据 |
| G4 Generic | fail-closed、PAGE_REVIEW、列确认、Temporary Template | 已实现（核心） | CLI/SQLite/re-export 和 Review GUI 映射向导已具备；仍需 holdout 与全新 Windows 验收 |
| G5 Validation | Decimal、四态规则、风险和可解释 finding | 部分完成 | 每条关键规则有明确 PASS/FAIL/INDETERMINATE/N/A 测试和 holdout 证据 |
| G6 结构复核 | move/merge/split/add/duplicate、审计和 source spans | 已实现（核心） | Review UI、数据库、导出和结构测试已通过；仍需全新 Windows 外部验收 |
| G7 Export | Excel、Review Excel、searchable PDF、Export Manifest | 工程完成 | 三类输出可读，Manifest hash 可复核；viewer/fallback benchmark 通过 |
| G8 Benchmark | Calibration、Regression、Locked Release Holdout | 未完成 | 500–1000 页，按 statement/account/layout 隔离，独立 truth 复核 |
| G9 Windows 发布 | 新机断网安装、运行、暂停/恢复、升级/回滚、卸载 | 未完成 | 全流程在干净 Windows x64 机器复现；本机启动探针和 process 运行不替代此验收 |
| G10 供应链与信誉 | 签名、SmartScreen、Defender、SBOM、license、字体 | 未完成 | 归档签名、扫描、许可证和字体授权证据 |

## 当前已完成的工程项

- SQLite schema 已为 v6，保存稳定 TextBlock ID、字段级 source spans、结构复核和 Run-scoped Temporary Template；
- Native Text Quality Gate 失败时进入 OCR fallback，native block 不伪造 confidence；
- Generic 关键列无法可靠映射时返回 `PAGE_REVIEW`，可用 `bankocr-template` 或 Review GUI 确认并恢复重跑；
- Review GUI 支持移动、合并、拆分、补行和标记重复，结构操作写入 `review_events`；
- Validation Issue 支持四态规则语义并持久化；
- Excel 业务字段优先，Source Index 保留来源证据；
- CLI 和任务队列每次生成带 SHA-256 的 `*.export-manifest.json`；
- 原始 PDF 不被输出覆盖，项目 run 保存源文件 SHA-256；
- 当前 4 页 PoC 已通过既有门槛，但不等于正式发布门槛。

## 正式发布前不得忽略的缺口

1. Temporary Template 自动转正式模板；
2. anchor/table-local 模板坐标；
3. 分层 benchmark、第二人 truth 复核和 Silent Critical Error 统计；
4. searchable PDF viewer/fallback 证据；
5. 新机断网 Windows、签名、SmartScreen/Defender、SBOM/license 和 CJK 字体授权。

只有当 G1–G10 全部有可复核证据，负责人才能创建正式 release tag。当前 release candidate 可以供开发验收使用，但必须把输出目录中的 `*.export-manifest.json` 与三类文件一起保存，便于之后复核 hash。
