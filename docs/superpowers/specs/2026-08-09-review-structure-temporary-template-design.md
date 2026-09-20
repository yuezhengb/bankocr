# Structured Review and Temporary Template Design

## Goal

补齐 V1.1 中当前可以在现有 Windows 开发机完成的两个能力：

1. 人工复核不再只能修改字段值，而是可以对交易行做移动、合并、拆分、补录和标记重复。
2. 未知版式在 `PAGE_REVIEW` 后可以由复核员确认列映射，生成**仅限当前 Run** 的 Temporary Template，并在该 Run 的后续处理/重跑中复用。

两项能力都必须保留 OCR 原文、建议值、最终值和来源坐标，且每次结构变化都写入 SQLite 审计事件。

## Decisions

### 1. Candidate identity 与展示顺序分离

`page_index + row_index` 继续作为 OCR 来源行身份，不因“移动”而重写；新增可选 `review_order` 作为同页人工展示/导出顺序。这样移动交易不会伪造来源行，也不会丢失 `source_spans`。

### 2. Duplicate 是显式状态

`CandidateStatus.DUPLICATE` 搭配 `duplicate_of=(page_index, row_index)`。重复行仍保留在数据库和审计中，但导出层明确显示其状态，后续正式业务导出不得把它当作有效交易；标记重复不是静默删除。

### 3. 结构操作在纯模型中完成

`ReviewSession` 负责不可变地生成新候选集合和 `ReviewOperation` 日志：

- `move_candidate(index, target_index)`：同页移动，更新 `review_order`。
- `merge_candidates(first, second)`：合并同页两行，保留两行全部来源跨度；冲突字段拼接为待复核值。
- `split_candidate(index, field_names)`：把选定字段拆成新行，两个结果均回到待复核。
- `add_candidate(candidate, position)`：补录缺失交易；若 row identity 冲突，分配同页新的 row index。
- `mark_duplicate(index, duplicate_of_index)`：保留重复行并关联原行。

结构操作默认 fail-closed：跨页合并/拆分、空字段拆分、自指重复、重复 row identity 都直接报错。

### 4. SQLite 以页面快照保存结构复核

普通字段复核继续使用现有 upsert 路径；包含结构操作的保存使用 `save_structure_review`：

- 对每个受影响页面在一个事务内替换候选快照；
- 先校验同页 `(page_index, row_index)` 唯一、来源跨度合法、重复指向存在；
- 为每个结构操作写 `review_events`，事件 `before_json/after_json` 保存操作前后候选快照及操作参数；
- 同时重跑文档级验证并刷新页面/Run 状态。

### 5. Temporary Template 是 Run-scoped 数据，不进入正式模板包

Temporary Template 由确认后的 `TableTemplate` 加上来源页、确认人、确认时间组成，写入 `temporary_templates` 表，主键为 `run_id`。其 ID 使用 `temporary:run-{run_id}:page-{page_index}`，不能被 `templates/known` 的 manifest 指纹覆盖，也不能自动晋升为正式模板。

确认映射必须满足：列名唯一、比例合法、required fields 已声明、列边界不重叠。保存后同一 Run 的重跑通过 `temporary_templates` 加载该模板，优先于正式模板；换 Run 不会读取它。

### 6. GUI 先复用纯模型/服务接口

本阶段先让 `ReviewSession`、`ReviewService`、`ProjectStore` 和处理流水线具备可测试的完整语义，再在现有复核窗口接入按钮/确认对话框。这样即使 Qt 不可用，核心审计和离线批处理也不会依赖 GUI。

## Non-goals

- 本阶段不宣称完成 500–1000 页 Holdout、第二复核员、全新 Windows 断网、代码签名、字体授权或 SmartScreen/Defender 外部验收。
- 不把 Temporary Template 自动写入正式 known-template 目录。
- 不允许结构操作绕过确定性验证或把 PAGE_REVIEW 静默改成成功。

## Acceptance criteria

- 结构操作单元测试覆盖 provenance、状态、顺序、非法操作和 round-trip SQLite。
- schema v5 数据库可迁移到新版本；旧候选可正常读取。
- Temporary Template 可确认、保存、按 Run 隔离加载，并可注入 `DocumentProcessor`/`ProjectRunService` 的重跑路径。
- 全量 pytest、compileall、pip check 通过；真实样本至少重新跑 CLI/benchmark 以证明既有 known-template 路径不退化。
