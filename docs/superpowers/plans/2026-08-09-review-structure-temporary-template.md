# Structured Review and Temporary Template Implementation Plan

> 执行规则：每个任务先写失败测试，测试通过后再进入下一任务；每个任务完成后运行相关测试和 `git diff --check`。

## Task 1 — Domain model and review session

**Files:** `src/bankocr/parser/models.py`, `src/bankocr/domain/review.py`, `src/bankocr/gui/review_model.py`, `tests/unit/gui/test_review_model.py`

**Steps:**

1. 添加 `DUPLICATE`、`duplicate_of` 和 `review_order`，保持旧构造器兼容。
2. 添加不可变 `ReviewOperation`。
3. 为移动、合并、拆分、补录、标重复写失败测试，再实现。
4. 测试每个操作的来源跨度、raw/suggested/final 分层和非法输入。

**Gate:** 纯 Python review model tests 全部通过；没有 SQLite/Qt 依赖。

## Task 2 — Storage schema and audit

**Files:** `src/bankocr/storage/project_store.py`, `tests/unit/storage/test_project_store.py`

**Steps:**

1. 写 v5→v6 migration tests。
2. 添加 candidate duplicate/order 列和 `temporary_templates` 表。
3. 实现 structure-review transactional snapshot replacement、校验和审计事件。
4. 实现 candidate/temporary-template round-trip tests。

**Gate:** 新数据库和 v5 数据库迁移都可用；失败事务不留下半套候选。

## Task 3 — Review service integration

**Files:** `src/bankocr/pipeline/review_service.py`, `src/bankocr/gui/app.py`, `src/bankocr/gui/main_window.py`, related tests

**Steps:**

1. 让服务保存 `ReviewSession`，结构操作走新的原子存储接口。
2. 保留现有 `save(candidates)` 兼容路径。
3. 复核窗口增加最小结构操作入口/回调；UI 失败不影响核心服务。

**Gate:** 现有字段复核测试不退化，结构保存后可重新加载并看到审计事件。

## Task 4 — Temporary Template confirmation and run isolation

**Files:** `src/bankocr/parser/temporary_template.py`, `src/bankocr/parser/template_pack.py`, `src/bankocr/pipeline/processor.py`, `src/bankocr/pipeline/run_service.py`, related tests

**Steps:**

1. 先测试确认映射、范围校验、序列化和 Run 隔离。
2. 实现 `TemporaryTemplateConfirmation`/builder 及 ProjectStore persistence。
3. 注入 DocumentProcessor 的 page-scoped template override；ProjectRunService 自动加载当前 Run 模板。
4. 测试 formal template fallback、temporary priority 和换 Run 不串模板。

**Gate:** 未知版式仍 fail-closed；确认后只在同一 Run 可复用。

## Task 5 — Local acceptance assets and verification

**Files:** `scripts/`, `docs/`, `tests/`

**Steps:**

1. 增加结构复核/Temporary Template 验收命令或 fixture。
2. 更新 implementation status / release gate，明确外部验收未完成项。
3. 运行全量 pytest、compileall、pip check、真实 PDF benchmark/CLI smoke。
4. 提交并推送当前分支，记录 commit 和验证证据。

**Gate:** 只对实际完成的本地项打勾；外部项保持 pending。
