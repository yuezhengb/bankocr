# Windows x64 离线打包

本目录说明 BankOCR 的 Windows 构建、离线组包与校验流程。`bankocr-gui.exe` 是面向桌面用户的无参数入口；它运行时只读取与 EXE 同级的资源目录。

## 构建 Windows 程序

在 Windows x64 的项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gui,packaging]"
.\scripts\build_windows.ps1 -Backend auto
```

可使用 `-Backend nuitka` 或 `-Backend pyinstaller` 固定构建器。GUI 构建必须保持无控制台窗口：Nuitka 使用 `--windows-console-mode=disable`，PyInstaller 规格文件使用 `console=False`。

## 组装无参数 GUI 离线包

`build_offline_bundle.py` 仅接受新的或空的输出目录，不会清除已有目录。为保证普通员工双击 GUI 后即可运行，传入 GUI EXE 时必须同时传入可分发的 CJK 字体；脚本会把它固定命名为 `fonts\msyh.ttc`。

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\build_offline_bundle.py `
  --wheel work\wheel\bankocr-0.1.0-py3-none-any.whl `
  --requirements requirements-lock.txt `
  --model-dir C:\BankOCR\models `
  --manifest C:\BankOCR\models\manifest.json `
  --template-dir templates\known `
  --template-manifest templates\manifest.json `
  --executable work\windows-build\bankocr-process.exe `
  --review-executable work\windows-build\bankocr-review.exe `
  --gui-executable work\windows-build\bankocr-gui.exe `
  --font-file C:\Windows\Fonts\msyh.ttc `
  --output-dir work\release-v1-new
```

组包后，以下资源必须与 `bankocr-gui.exe` 保持同级，交付或迁移时不可拆分：

```text
release-v1-new/
├── bankocr-gui.exe
├── models/
│   ├── manifest.json
│   ├── PP-OCRv6_det_small.onnx
│   ├── ch_ppocr_mobile_v2.0_cls_mobile.onnx
│   └── PP-OCRv6_rec_small.onnx
├── templates/
│   ├── manifest.json
│   └── known/
└── fonts/
    └── msyh.ttc
```

组包会在 `release.json` 和 `release-metadata.json` 中记录离线资源、CJK 字体和 SHA-256 元数据。GUI 启动时默认把用户数据写入“文档\BankOCR”，输出文件夹为“文档\BankOCR\输出”。

## 校验离线包

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\verify_offline_release.py `
  --model-dir work\release-v1-new\models `
  --manifest work\release-v1-new\models\manifest.json `
  --release-dir work\release-v1-new
```

代码签名、全新断网 Windows 验收、SmartScreen/Defender、授权与其他正式发布门槛的状态和证据要求，统一见 [`docs/v1-release-gate.md`](../../docs/v1-release-gate.md)。本说明不将这些外部门槛表述为已通过。
