# Final Review Fix Report

**基线：** `4ca4f8b7ba82559917bc769389437d69684ef126`
**修复波次：** final review Important 1-4
**日期：** 2026-08-09

## 改动文件

- `src/bankocr/gui/main_window.py`
  - 增加统一 `_queue_is_running()` / `_guard_store_action()` / review-window guard。
  - 队列运行期间禁用结果、复核、继续、重试等危险动作，保留暂停/取消入口。
  - 已打开 Review 窗口时拒绝启动队列；Review 保存和 Temporary Template 回调再次检查队列状态。
  - Review 保存后调用 `queue.update_result()`，把重新导出的 artifacts 和 `store.page_states(run_id)` 的真实 `needs_review_count` 写回当前 completed task result。
  - 任务/队列异常写 UTF-8 本地日志，并在界面显示中文摘要，不再直接展示内部异常文本。
- `src/bankocr/gui/error_reporting.py`
  - 新增 GUI 错误摘要和本地日志写入工具。
  - 日志至少记录时间、context、task/source/output、异常类型和 traceback；日志失败会被吞掉，不覆盖原错误流程。
- `src/bankocr/gui/runtime.py`
  - 默认字体解析只接受 `resource_root/fonts/msyh.ttc`。
  - 显式 `--font-file` 仍验证存在并作为诊断覆盖。
- `src/bankocr/gui_cli.py`
  - 启动异常和缺资源启动门禁写入 `BankOCR\日志`。
  - 将 `log_root` 传入主窗口。
- `src/bankocr/task/manager.py`
  - 新增受控 `TaskManager.update_result()`，仅允许更新当前 completed attempt。
- `src/bankocr/task/document_queue.py`
  - 新增 `PdfTaskQueue.update_result()` facade。
- `tests/unit/gui/test_main_window.py`
  - 增加真实 GUI guard、Review 保存刷新 result、任务异常日志与中文摘要测试。
- `tests/unit/gui/test_runtime.py`
  - 增加“系统字体存在但 bundled font 缺失仍不回退”测试。
- `tests/unit/task/test_document_queue.py`
  - 增加 completed task result 受控更新测试。
- `tests/unit/test_gui_cli.py`
  - 增加启动异常日志落盘和日志失败不崩测试。

## 设计决策

1. **并发策略：选择 GUI guard，而不是改 SQLite 连接模型。**
   本波次目标是最小可靠修复。现有 `ProjectStore` 单连接假设继续保留，GUI 在队列 worker 运行期间禁止打开/保存 Review、Temporary Template、继续/重试/打开结果等可能触碰同一 store 或当前 snapshot 的操作。

2. **复核后刷新 task snapshot，而不是只改 label。**
   `TaskManager.update_result()` 只允许 completed attempt，避免 queued/running/failed 状态被随意改写。Review 保存后从持久化 store 读取 `page_states(run_id)` 统计 `needs_review_count`，并把重新导出的 artifacts 写回任务 result；主窗口 `_review_item_count()` 优先读取该持久化刷新值。

3. **零配置字体门禁 fail-closed。**
   默认路径不再查找 Windows 系统字体；如果 `resource_root/fonts/msyh.ttc` 缺失，`font_file` 为 `None`，由启动门禁报告缺 CJK 字体。显式 `--font-file` 仍可用于诊断，并继续验证文件存在。

4. **错误面向员工、日志面向管理员。**
   GUI 摘要映射常见 `FileNotFoundError` / `PermissionError` / 输出 `OSError` 为中文简明提示并带源文件、输出目录或日志位置；完整异常类型和 traceback 进入 UTF-8 日志。日志写入失败不会影响原有失败返回或界面提示。

## 验证命令与结果

### 相关 GUI/CLI/runtime/manager 测试

命令：

```powershell
$env:PYTHONPATH='src'; $env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-targeted-fix tests\unit\gui\test_main_window.py tests\unit\gui\test_runtime.py tests\unit\task\test_document_queue.py tests\unit\test_gui_cli.py -q
```

结果：

```text
29 passed in 0.71s
```

退出码：`0`

### 受影响的整个测试集

命令：

```powershell
$env:PYTHONPATH='src'; $env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-final-fix -q
```

结果：

```text
........................................................................ [ 29%]
........................................................................ [ 58%]
........................................................................ [ 87%]
................................                                         [100%]
248 passed in 3.78s
```

退出码：`0`

### compileall

命令：

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
```

结果：无输出。
退出码：`0`

### pip check

命令：

```powershell
.\.venv\Scripts\pip.exe check
```

结果：

```text
No broken requirements found.
```

退出码：`0`

### git diff --check

命令：

```powershell
git diff --check
```

结果：

```text
warning: in the working copy of 'src/bankocr/gui/runtime.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'src/bankocr/task/document_queue.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'src/bankocr/task/manager.py', LF will be replaced by CRLF the next time Git touches it
```

退出码：`0`

## 剩余顾虑

- 本波次没有改变外部发布 Gate 状态，也没有声称断网 Windows、签名、SmartScreen/Defender、字体授权、SBOM 等未验证项通过。
- `git diff --check` 仍显示 Git 换行符提示，但退出码为 0，未发现 whitespace error。

---

# Retry Button Regression Follow-up

**日期：** 2026-08-09
**基线：** `be647d77389c1b0ca87cf7a41d8748861031c8ca`

## 问题

`src/bankocr/gui/main_window.py` 的 `_update_result_actions()` 在队列空闲时用 `has_completed_result` 控制“重试”按钮，导致 `failed` / `cancelled` 任务无法通过 GUI 重新排队；底层 `TaskManager.restart()` 支持 `completed` / `failed` / `cancelled`。

## 改动文件

- `src/bankocr/gui/main_window.py`
  - 队列运行期间继续禁用重试按钮。
  - 队列空闲时，“重试”按钮改为在选中任务状态属于 `completed` / `failed` / `cancelled` 时启用。
  - 未放宽 `TaskManager.update_result()` 边界。
- `tests/unit/gui/test_main_window.py`
  - 新增 failed 任务 GUI 重试测试：刷新窗口后按钮可用，调用 `_restart_selected()` 后状态进入 `queued`。
  - 新增 cancelled 任务 GUI 重试测试：刷新窗口后按钮可用，调用 `_restart_selected()` 后状态进入 `queued`。

## 验证命令与结果

### 新增回归测试

```powershell
$env:PYTHONPATH='src'; $env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-retry-green tests\unit\gui\test_main_window.py::test_main_window_enables_retry_for_failed_task tests\unit\gui\test_main_window.py::test_main_window_enables_retry_for_cancelled_task -q
```

```text
..                                                                       [100%]
2 passed in 0.30s
```

退出码：`0`

### 覆盖 GUI 测试

```powershell
$env:PYTHONPATH='src'; $env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-retry-window tests\unit\gui\test_main_window.py -q
```

```text
..........                                                               [100%]
10 passed in 0.43s
```

退出码：`0`

### 全量 pytest

```powershell
$env:PYTHONPATH='src'; $env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-retry-final -q
```

```text
........................................................................ [ 28%]
........................................................................ [ 57%]
........................................................................ [ 86%]
..................................                                       [100%]
250 passed in 3.09s
```

退出码：`0`

### compileall

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
```

结果：无输出。
退出码：`0`

### pip check

```powershell
.\.venv\Scripts\pip.exe check
```

```text
No broken requirements found.
```

退出码：`0`

### git diff --check

```powershell
git diff --check
```

```text
warning: in the working copy of 'src/bankocr/gui/main_window.py', LF will be replaced by CRLF the next time Git touches it
```

退出码：`0`

## 剩余顾虑

- 未改动外部发布 Gate，也未改变未验证结论。
- `git diff --check` 仅有 LF/CRLF 提示，无 whitespace error。
