# Task 5 — BankOCR 零配置 GUI 内部 release candidate 验收报告

**执行日期：** 2026-08-09
**结果：** `DONE_WITH_CONCERNS`

## 范围与输入

本次只生成新的候选资产，未覆盖旧 release。仓库根目录 `models` 仅含 README，未被作为模型输入。

| 项目 | 实际使用路径 |
|---|---|
| 模型包 | `work\release-candidate-20260809-v12\models` |
| 模型 manifest | `work\release-candidate-20260809-v12\models\manifest.json` |
| 模板包 | `templates\known` + `templates\manifest.json` |
| wheel | `work\release-wheel-v12\bankocr-0.1.0-py3-none-any.whl` |
| 字体 | `work\release-candidate-20260809-v12\fonts\msyh.ttc` |
| Windows 构建输出 | `work\windows-build-v13`（新建） |
| 候选包输出 | `work\release-candidate-20260809-gui`（新建） |

## 自动化验证

| 命令 | 结果 |
|---|---|
| `PYTHONPATH=src; QT_QPA_PLATFORM=offscreen; .venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp -q` | **240 passed in 3.31s** |
| `.venv\Scripts\python.exe -m compileall -q src tests scripts` | 退出码 0、无错误输出 |
| `.venv\Scripts\python.exe -m pip check` | `No broken requirements found.` |

`build_windows.ps1` 的直接调用受本机 PowerShell 执行策略阻止；使用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Backend pyinstaller -OutputRoot work\windows-build-v13` 后完成构建。输出目录检查到四个 PyInstaller EXE：

| 资产 | 大小（字节） |
|---|---:|
| `bankocr-process.exe` | 141,269,164 |
| `bankocr-template.exe` | 9,314,562 |
| `bankocr-review.exe` | 90,200,199 |
| `bankocr-gui.exe` | 179,254,337 |

## 候选包与离线资产核验

`build_offline_bundle.py` 已组装 `work\release-candidate-20260809-gui`。`verify_offline_release.py` 对候选包和模型 manifest 验证通过：

```text
model_fingerprint=787666f230518edd1dcdd389828d45faa7c4f45de48490f08d0eed2e11d3dd38
offline_model_pack=ok
```

| 文件 | SHA-256 |
|---|---|
| `release.json` | `9d48bcc98d88ded57bedb35491148f462292c61b3d270a6dcfb9d63cc2da1e13` |
| `bankocr-process.exe` | `38b37dd2fbf91b7eb148f06079ef420db1ab21d6f4fba5c2f72acf0264ce1c00` |
| `bankocr-gui.exe` | `073ddbe843528c74fd933168ea3d2ebfec4124a030c45ba0c3203300562de789` |

## 本机可执行验收

候选包内的 `bankocr-process.exe` 显式使用候选包内 models、templates 和字体，成功处理：

```text
C:\BankOCR\samples\example-statement.pdf
```

新输出目录：`work\local-acceptance-20260809-process`。

summary 报告 2 页；export manifest 包含 `excel`、`review_excel`、`searchable_pdf`，`unresolved_count=0`。Excel、searchable PDF、summary、export manifest 和 Review Excel 均存在。

| 文件 | SHA-256 |
|---|---|
| `example-statement.xlsx` | `454df2fca229a418c5ff3d4b31f1eb243645057baf832783ac1ca92eb7a08101` |
| `example-statement.review.xlsx` | `af6b85b5fb2c531a70ea0090e8f263d56b6bbd5e7bc0ee876b4657f26b6fceba` |
| `example-statement.searchable.pdf` | `48c3a5d918fd1636ab76fa9337e80591678abac850edda0c1dba8f2362956223` |
| `example-statement.summary.json` | `e19e56ab2ca0f0ee050c6e88290314a46d50a60671eb4dca00f916c7b1ebeebd` |
| `example-statement.export-manifest.json` | `52b08e7b5ec6b4206c9768eb2ac96065d0ddd1d9bd3f87a33e2148a3466a8336` |

## GUI 启动探针

无参数启动新 `bankocr-gui.exe` 后，两个同路径进程（bootstrap 与 GUI）均保持存活超过 5 秒，探针进程随后已停止清理。该记录只证明本机无参数启动探针成功。

未执行人工 GUI 验收：未在 GUI 中选择 PDF、点击处理、检查 Review 动作或确认界面内容。因此不能将本条记录表述为 GUI 手工验收通过。

## 未关闭的外部 Gate / 顾虑

该候选包仍不是正式 V1。以下项目均未在本任务中验证：

- locked release holdout 和 500–1000 页分层 benchmark；
- 独立第二人 truth 复核与 Silent Critical Error 统计；
- 全新、干净、断网 Windows x64 的安装/卸载及端到端验收；
- Authenticode 签名；
- SmartScreen 与 Defender 检查；
- CJK 字体授权；
- 第三方许可证与 SBOM 审查；
- searchable PDF viewer/fallback benchmark；
- 人工 GUI 文件选择、处理和 Review 流程验收。

## 2026-08-09 复核补充证据

实际重跑的原始验证日志位于 `docs/verification/2026-08-09-zero-config-gui/`；每项 `.log` 都包含命令、cwd、适用环境变量、git SHA、开始/结束时间、exit code，以及原始 stdout/stderr，旁边保留独立的 `.stdout.log` / `.stderr.log`。

| 证据 | 实际结果 |
|---|---|
| `pytest.log` | `240 passed in 2.89s`，exit code 0 |
| `compileall.log` | exit code 0，stdout/stderr 均为空 |
| `pip-check.log` | `No broken requirements found.`，exit code 0 |
| `offline-verify.log` | fingerprint `787666f230518edd1dcdd389828d45faa7c4f45de48490f08d0eed2e11d3dd38`，exit code 0 |
| `process-acceptance.log` | 对新的 `work\local-acceptance-20260809-process-reverify-2` 实际运行；五项输出检查均为 True，exit code 0 |

`gui-launch-probe.json` 是无参数启动的机器可读记录：新启动 PID `29672`，观察 5 秒后仍存活；cleanup 成功且无残留目标进程，根进程在强制结束后的 exit code 为 `-1`。该探针仍只证明无参数启动，不构成 GUI 手工点击流程验收。

## 2026-08-09 Important 证据链修复：process acceptance reverify-2 hashes

本节只补齐 Task 5 证据链中 `process-acceptance.log` 与报告 hash 表对应目录不一致的问题；未修改程序逻辑，也不改变 release gate 结论。

### 目录区分

| 类型 | 目录 | 说明 |
|---|---|---|
| 初次本机验收目录 | `work/local-acceptance-20260809-process` | 上文“本机可执行验收”中的 5 项 SHA-256 表对应此目录。 |
| 补充重跑目录 | `work/local-acceptance-20260809-process-reverify-2` | `docs/verification/2026-08-09-zero-config-gui/process-acceptance.log` 记录的实际 process acceptance 重跑目录；本节下方列出其 5 项产物 SHA-256。 |

### 补充重跑产物 SHA-256

机器可读 manifest 已归档为 `docs/verification/2026-08-09-zero-config-gui/process-acceptance-reverify-2-sha256.json`，并已在 `process-acceptance.log` 的 `sha256-manifest` 小节中引用。

| 相对文件名 | SHA-256 |
|---|---|
| `example-statement.xlsx` | `97c10f242ceee500353948df8640daf79b176e60f8c1b4c7373bc84cc88c908d` |
| `example-statement.review.xlsx` | `e8481e8be746bc74483945d4982fe16644b76943f042c7f434ab82a92d2f3642` |
| `example-statement.searchable.pdf` | `7108bf8bda3189129f4251c2cce6d746896a9aa4511928b6694a1adf63571720` |
| `example-statement.summary.json` | `e19e56ab2ca0f0ee050c6e88290314a46d50a60671eb4dca00f916c7b1ebeebd` |
| `example-statement.export-manifest.json` | `e9ad6833fcb790d020a7816fb750bc23f93bbc204bfe775f5e011359a1f4dc48` |

### 本次修复验证记录

- 读取并解析 `docs/verification/2026-08-09-zero-config-gui/process-acceptance-reverify-2-sha256.json`。
- 对 `work/local-acceptance-20260809-process-reverify-2` 下 5 个实际产物重新计算 SHA-256。
- 验证 manifest 中的 `run_directory`、5 个相对文件名、文件大小和 SHA-256 均与当前文件系统产物一致。

实际执行命令：

```powershell
@'
from pathlib import Path
import hashlib, json

manifest_path = Path('docs/verification/2026-08-09-zero-config-gui/process-acceptance-reverify-2-sha256.json')
log_path = Path('docs/verification/2026-08-09-zero-config-gui/process-acceptance.log')
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
expected_dir = 'work/local-acceptance-20260809-process-reverify-2'
assert manifest['algorithm'] == 'sha256', manifest['algorithm']
assert manifest['run_directory'] == expected_dir, manifest['run_directory']
assert len(manifest['files']) == 5, len(manifest['files'])
log_text = log_path.read_text(encoding='utf-8')
assert str(manifest_path).replace('\\', '/') in log_text
for entry in manifest['files']:
    path = Path(entry['relative_path'])
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    actual_size = path.stat().st_size
    assert actual_hash == entry['sha256'], (entry['filename'], actual_hash, entry['sha256'])
    assert actual_size == entry['size_bytes'], (entry['filename'], actual_size, entry['size_bytes'])
    print(f"OK {entry['filename']} size={actual_size} sha256={actual_hash}")
print('manifest_ok=true')
print('files_checked=5')
print(f"run_directory={manifest['run_directory']}")
'@ | .venv\Scripts\python.exe -
```

输出：

```text
OK example-statement.xlsx size=32698 sha256=97c10f242ceee500353948df8640daf79b176e60f8c1b4c7373bc84cc88c908d
OK example-statement.review.xlsx size=5295 sha256=e8481e8be746bc74483945d4982fe16644b76943f042c7f434ab82a92d2f3642
OK example-statement.searchable.pdf size=12497574 sha256=7108bf8bda3189129f4251c2cce6d746896a9aa4511928b6694a1adf63571720
OK example-statement.summary.json size=978 sha256=e19e56ab2ca0f0ee050c6e88290314a46d50a60671eb4dca00f916c7b1ebeebd
OK example-statement.export-manifest.json size=941 sha256=e9ad6833fcb790d020a7816fb750bc23f93bbc204bfe775f5e011359a1f4dc48
manifest_ok=true
files_checked=5
run_directory=work/local-acceptance-20260809-process-reverify-2
```

未完成外部 gates、人工 GUI 文件选择/处理/Review 验收、正式 V1 release tag 的限制保持原结论：当前仍只是 release candidate，不是正式 V1。
