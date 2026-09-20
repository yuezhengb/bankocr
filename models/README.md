# Offline OCR model pack

运行时不会下载模型。将以下三个 RapidOCR ONNX 文件放入本目录：

- `PP-OCRv6_det_small.onnx`
- `ch_ppocr_mobile_v2.0_cls_mobile.onnx`
- `PP-OCRv6_rec_small.onnx`

然后生成并保存校验清单：

```powershell
python scripts/create_model_manifest.py `
  --model-dir models `
  --output models/manifest.json
```

处理时显式指定模型目录和清单：

```powershell
bankocr-process statement.pdf `
  --model-dir models `
  --model-manifest models/manifest.json `
  --output-dir output
```

模型二进制和含有具体哈希的 `manifest.json` 不提交代码仓库；发布包必须通过独立的离线资产验收：

```powershell
python scripts/verify_offline_release.py `
  --model-dir models `
  --manifest models/manifest.json
```
