# Golden Sample 标注格式

Golden Sample 只保存人工确认后的字段值和页面/行键，不保存原始 PDF、截图或 OCR 原文。真实样本应放在本地受控目录；仓库只提交脱敏的结构示例。

```json
{
  "sample_id": "synthetic-grid-v1",
  "transactions": [
    {
      "page_index": 0,
      "row_index": 2,
      "fields": {
        "transaction_date": "2026-01-02",
        "transaction_amount": "12.30",
        "balance": "100.00"
      }
    }
  ]
}
```

加载标注：

```python
from bankocr.benchmark.golden import load_golden_sample

sample = load_golden_sample("truth.json")
```

`page_index` 和 `row_index` 组成唯一键；重复键、负数索引和非字符串字段值会直接失败，避免把不完整标注带入回归门禁。
