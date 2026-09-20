# BankOCR 零配置 GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 BankOCR 主 GUI 改造成普通员工双击即可使用的 Windows x64 离线程序，自动使用安装包资源，并把结果统一保存到 Windows“文档\BankOCR\输出”。

**Architecture:** 新增一个纯路径/资源解析层，负责定位 Windows 文档目录、用户数据目录和可执行文件旁的模型/模板/字体；`gui_cli.py` 使用该层提供零参数默认配置，同时保留现有命令行参数作为诊断覆盖入口。主窗口继续复用现有 `PdfTaskQueue`、SQLite、复核和导出逻辑，只增加结果打开按钮、清晰中文状态和启动错误对话框。

**Tech Stack:** Python 3.12；PySide6；PyMuPDF；SQLite；PyInstaller；pytest。

## Global Constraints

- 普通员工不需要 PowerShell、Python 或命令行参数。
- 发布目录必须包含 `bankocr-gui.exe`、`models`、`templates\known` 和可用 CJK 字体资源。
- 默认数据目录为 Windows“文档”目录下的 `BankOCR`，输出目录为 `文档\BankOCR\输出`。
- 原始 PDF 永不覆盖、永不移动。
- 模型和模板继续通过本地 manifest/hash 验证；运行时不得下载资源。
- OCR raw、secondary、suggested、final 和人工复核记录继续分层保存。
- 500–1000 页 Holdout、独立复核、全新断网 Windows、签名、SmartScreen/Defender、字体授权和许可证审查继续保持未验证状态。
- 在外部发布门槛完成前，产物名称继续使用 `release-candidate`。

---

### Task 1: Add zero-configuration runtime path resolution

**Files:**
- Create: `src/bankocr/gui/runtime.py`
- Create: `tests/unit/gui/test_runtime.py`

**Interfaces:**
- Produces `GuiRuntimePaths` with `resource_root`, `data_root`, `output_root`, `project_db`, `log_root`, `model_dir`, `model_manifest`, `template_dir`, and `font_file`.
- Produces `resolve_gui_paths(...) -> GuiRuntimePaths`.
- Produces `missing_runtime_resources(paths: GuiRuntimePaths) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing path tests**

```python
def test_resolve_gui_paths_uses_documents_bankocr_and_adjacent_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "windows_documents_dir", lambda: tmp_path / "Documents")
    root = tmp_path / "package"
    (root / "models").mkdir(parents=True)
    (root / "models" / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "templates" / "known").mkdir(parents=True)
    paths = runtime.resolve_gui_paths(resource_root=root)
    assert paths.output_root == tmp_path / "Documents" / "BankOCR" / "输出"
    assert paths.project_db == tmp_path / "Documents" / "BankOCR" / "项目" / "project.sqlite3"
    assert paths.model_dir == root / "models"
    assert paths.template_dir == root / "templates" / "known"


def test_missing_runtime_resources_reports_each_missing_asset(tmp_path):
    paths = runtime.resolve_gui_paths(resource_root=tmp_path, data_root=tmp_path / "data")
    assert "models" in runtime.missing_runtime_resources(paths)
    assert "model manifest" in runtime.missing_runtime_resources(paths)
    assert "known templates" in runtime.missing_runtime_resources(paths)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\gui\test_runtime.py -q`

Expected: FAIL because `bankocr.gui.runtime` and `GuiRuntimePaths` do not exist.

- [ ] **Step 3: Implement the runtime resolver**

Implement:

```python
@dataclass(frozen=True, slots=True)
class GuiRuntimePaths:
    resource_root: Path
    data_root: Path
    output_root: Path
    project_db: Path
    log_root: Path
    model_dir: Path
    model_manifest: Path
    template_dir: Path
    font_file: Path | None

def resolve_gui_paths(
    *,
    resource_root: str | Path | None = None,
    data_root: str | Path | None = None,
    project_db: str | Path | None = None,
    model_dir: str | Path | None = None,
    model_manifest: str | Path | None = None,
    template_dir: str | Path | None = None,
    font_file: str | Path | None = None,
) -> GuiRuntimePaths: ...
```

`resource_root` defaults to the frozen executable directory when `sys.frozen` is true, otherwise to the repository root. `data_root` defaults to `windows_documents_dir() / "BankOCR"`. `font_file` first checks `resource_root / "fonts" / "msyh.ttc"`, then the Windows system font locations; an explicitly supplied missing font remains an error. `windows_documents_dir()` uses the Windows known-folder API when available and falls back to `Path.home() / "Documents"`.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\gui\test_runtime.py -q`

Expected: all focused tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bankocr/gui/runtime.py tests/unit/gui/test_runtime.py
git commit -m "feat: add zero-config GUI runtime paths"
```

### Task 2: Make `gui_cli.py` start without arguments

**Files:**
- Modify: `src/bankocr/gui_cli.py`
- Create: `tests/unit/test_gui_cli.py`

**Interfaces:**
- `main([])` resolves default paths and starts the GUI.
- Existing flags `--project-db`, `--model-dir`, `--model-manifest`, `--template-dir`, `--output-dir`, `--font-file`, and `--low-resource` remain accepted as diagnostic overrides.
- Missing assets are shown through a PySide6 critical error dialog and return exit code `2` instead of raising an unhandled traceback.

- [ ] **Step 1: Write failing CLI tests**

Test that `build_parser().parse_args([])` accepts an empty argument list, that `main()` passes resolved paths into `ModelPack`, `DocumentProcessor`, `ProjectStore`, and `PdfTask`, and that a missing model pack returns `2` after calling the startup-error presenter. Use monkeypatches for `run_main`, `ModelPack.from_manifest`, `RapidOCRBackend`, `DocumentProcessor`, `ProjectStore`, `PdfTaskQueue`, and `show_startup_error` so the test never starts a real Qt loop or OCR engine.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_gui_cli.py -q`

Expected: FAIL because the required parser arguments reject `[]`.

- [ ] **Step 3: Implement zero-argument startup**

Make GUI path arguments optional, call `resolve_gui_paths`, create `data_root`, `output_root`, and `log_root`, validate `missing_runtime_resources`, then load the local model pack. Keep the real processing pipeline unchanged. Use `datetime.now().strftime("%Y%m%d-%H%M%S")` plus the SQLite project id for each task output directory:

```python
output_dir = paths.output_root / f"{source.stem}-{timestamp}-{project_id}"
```

Pass `paths.project_db`, `paths.model_dir`, `paths.model_manifest`, `paths.template_dir`, and `paths.font_file` into the existing pipeline. Add a small `show_startup_error(message: str) -> None` helper that creates `QApplication` and `QMessageBox.critical` without opening a console window.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_gui_cli.py -q`

Expected: all focused tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bankocr/gui_cli.py tests/unit/test_gui_cli.py
git commit -m "feat: allow zero-argument GUI startup"
```

### Task 3: Add beginner-friendly result actions to the main window

**Files:**
- Modify: `src/bankocr/gui/main_window.py`
- Modify: `tests/unit/gui/test_main_window.py`

**Interfaces:**
- `build_main_window(queue, task_factory, *, output_root: Path | None = None)` continues to support existing tests and callers.
- The main window exposes buttons for `打开输出文件夹`, `打开 Excel`, `打开可搜索 PDF`, and `开始人工复核`.
- Opening a result uses `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`; it never shells out to PowerShell.

- [ ] **Step 1: Write failing UI tests**

Add tests asserting that the window contains the Chinese result buttons, that a completed task exposes its `output_dir`, and that the result-opening helper chooses the `.xlsx` and `.searchable.pdf` artifacts from the task snapshot. Keep the existing queue-processing test unchanged except for asserting the new status text.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests\unit\gui\test_main_window.py -q`

Expected: FAIL because the new buttons and artifact-opening methods do not exist.

- [ ] **Step 3: Implement the simplified window behavior**

Keep drag-and-drop, queue processing, pause/resume/cancel/retry, and persisted review. Add a compact instruction label, a visible output-root label, result buttons, and a `QDesktopServices` helper. Enable result buttons only when the selected task has completed artifacts. Convert internal task statuses to clear Chinese text such as `等待处理`, `处理中`, `已完成`, `需要复核`, `失败` and show the number of review items rather than a raw exception when possible. Keep advanced queue controls available but place them after the main actions so a beginner sees the normal path first.

- [ ] **Step 4: Run focused GUI tests and verify they pass**

Run: `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests\unit\gui\test_main_window.py tests\unit\gui\test_review_window.py -q`

Expected: all GUI tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bankocr/gui/main_window.py tests/unit/gui/test_main_window.py
git commit -m "feat: add beginner-friendly GUI result actions"
```

### Task 4: Package the zero-config GUI and document employee usage

**Files:**
- Modify: `packaging/windows/bankocr-gui.spec`
- Modify: `scripts/build_offline_bundle.py`
- Modify: `packaging/windows/README.md`
- Modify: `README.md`
- Create: `docs/使用说明-普通员工.md`

**Interfaces:**
- A packaged `bankocr-gui.exe` can be double-clicked with no arguments.
- The release bundle retains adjacent `models`, `templates`, and `fonts` assets and copies the zero-config GUI executable.
- The user guide contains only employee-facing actions and the exact output location; release-gate notes remain in engineering docs.

- [ ] **Step 1: Add packaging acceptance checks**

Extend the bundle/release tests to assert that the release contains `bankocr-gui.exe`, `models\manifest.json`, the three ONNX files, `templates\known`, and `fonts\msyh.ttc`, and that the metadata still records `cjk_font_included` and `offline_assets_verified`.

- [ ] **Step 2: Run the packaging tests and verify any new assertion fails before the packaging change**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_offline_release.py tests\unit\test_release_metadata.py -q`

Expected: existing behavior remains green; any new zero-config metadata assertion must fail until the bundle metadata/readme changes are applied.

- [ ] **Step 3: Update packaging and employee documentation**

Keep `console=False`, include the adjacent resource layout, add the default GUI startup description, and add the Chinese employee guide with this workflow:

```text
双击 bankocr-gui.exe
→ 选择 PDF
→ 点击开始处理
→ 点击打开输出文件夹
→ 打开 Excel 或开始人工复核
```

Document that the whole release folder must be copied together and that the original PDF is not changed. Do not describe unverified external release gates as passed.

- [ ] **Step 4: Run documentation/package checks**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_offline_release.py tests\unit\test_release_metadata.py -q; git diff --check`

Expected: PASS and no whitespace errors.

- [ ] **Step 5: Commit**

```bash
git add packaging/windows/bankocr-gui.spec scripts/build_offline_bundle.py packaging/windows/README.md README.md docs/使用说明-普通员工.md tests
git commit -m "docs: package zero-config GUI for internal users"
```

### Task 5: Build and verify the internal release candidate

**Files:**
- Create during verification: `work/windows-build-v13/`
- Create during verification: `work/release-candidate-20260809-gui/`
- Update: `docs/implementation-status.md`
- Update: `docs/v1-release-gate.md`

**Interfaces:**
- The release candidate includes a no-argument GUI executable and the verified local asset pack.
- The status documents distinguish local verification from the retained external gates.

- [ ] **Step 1: Run the complete automated test suite**

Run:

```powershell
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp -q
.venv\Scripts\python.exe -m compileall -q src tests scripts
.venv\Scripts\python.exe -m pip check
```

Expected: all tests PASS, compileall produces no errors, and pip check reports no broken requirements.

- [ ] **Step 2: Build the Windows executables**

Run: `.\scripts\build_windows.ps1 -Backend pyinstaller -OutputRoot work\windows-build-v13`

Expected: `work\windows-build-v13\pyinstaller\dist\bankocr-gui.exe` exists alongside process, review, and template executables.

- [ ] **Step 3: Assemble a new release candidate**

Run:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe scripts\build_offline_bundle.py `
  --wheel work\release-wheel-v12\bankocr-0.1.0-py3-none-any.whl `
  --requirements requirements-lock.txt `
  --model-dir models `
  --manifest models\manifest.json `
  --template-dir templates\known `
  --template-manifest templates\manifest.json `
  --executable work\windows-build-v13\pyinstaller\dist\bankocr-process.exe `
  --template-executable work\windows-build-v13\pyinstaller\dist\bankocr-template.exe `
  --review-executable work\windows-build-v13\pyinstaller\dist\bankocr-review.exe `
  --gui-executable work\windows-build-v13\pyinstaller\dist\bankocr-gui.exe `
  --font-file work\release-candidate-20260809-v12\fonts\msyh.ttc `
  --output-dir work\release-candidate-20260809-gui
```

Expected: the command prints `work\release-candidate-20260809-gui` and creates a new, non-empty release directory. Do not overwrite an earlier release directory.

- [ ] **Step 4: Verify the offline asset pack**

Run `scripts\verify_offline_release.py` against the new model directory, manifest, and release directory. Expected: model fingerprint and release asset checks pass.

- [ ] **Step 5: Perform local GUI smoke acceptance**

Launch the new `bankocr-gui.exe` without arguments, choose `C:\BankOCR\samples\example-statement.pdf`, process it, and confirm that a new directory appears below the current user's `文档\BankOCR\输出`. Confirm Excel, searchable PDF, summary, export manifest, and the review action are present. Record the result path and hash in a local acceptance note.

- [ ] **Step 6: Update status without closing external gates**

Record the local GUI smoke result in `docs/implementation-status.md` and keep every external/unverified item already listed in `docs/v1-release-gate.md` explicitly open.

- [ ] **Step 7: Commit and push the implementation**

```bash
git add src tests packaging scripts docs README.md
git commit -m "feat: deliver zero-config internal GUI release candidate"
git push origin agent/v1-1-spec-audit
```

## Self-review checklist

- The design uses the existing queue and review services instead of duplicating OCR logic.
- Empty GUI arguments resolve to the adjacent model/template assets and user Documents directory.
- Output names include a timestamp and project id, so previous results are not overwritten.
- Missing assets fail visibly before OCR starts.
- The plan contains tests for path resolution, zero-argument startup, GUI result actions, package assets, and local acceptance.
- All unverified external release gates remain open and are not changed by the local implementation.
