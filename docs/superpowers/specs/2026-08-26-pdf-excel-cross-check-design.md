# PDF 与 Excel 对照核验设计

## 目标

让工作人员同时得到两种互补结果：

1. **结构化 Excel**：适合筛选、排序、统计和人工改正；
2. **核对版 PDF**：保留原始页面外观，并在可定位的交易区域画框、加编号，便于把 Excel 的一行直接对回 PDF。

Excel 不强行模拟 PDF 的固定页面排版，因为这样会失去筛选、统计和大文件稳定性。页面视觉一致性由 PDF 负责，表格结构一致性由 Excel 负责。

## 输出文件

同一份输入 `statement.pdf` 生成：

- `statement.xlsx`：主结果，含 `Transactions`、`Processing Report`、`Source Index`；
- `statement.review.xlsx`：待人工处理的问题；
- `statement.searchable.pdf`：原 PDF 页面加不可见 OCR 文字层，页面视觉不加框；
- `statement.comparison.pdf`：原 PDF 页面加 OCR 文字层、来源框和 `T0001` 等短编号；
- `statement.summary.json`：页级状态和运行摘要；
- `statement.export-manifest.json`：所有导出文件的大小和 SHA-256。

## 编号与来源规则

- 候选按 PDF 页码、复核顺序/行号排序，从 `T0001` 开始编号；
- `Transactions.comparison_id` 与核对版 PDF 的标签使用同一编号；
- `source_page` 使用人能直接理解的 1-based 页码；
- `source_bbox` 是候选所有字段来源框的并集，格式为 `x0,y0,x1,y1`；
- 优先使用 OCR 块索引；没有块索引时使用 `source_spans`；两者都没有时记录 `unlocated`，不在 PDF 上猜画位置；
- `Source Index` 仍保留字段级 raw/secondary/suggested/final 和来源证据。

## 核对版 PDF 颜色

- 绿色：候选已确认，且页面确定性校验通过；
- 黄色：尚未确认、待复核或校验不确定；
- 红色：该行存在关键失败；
- 灰色：重复或拒绝记录。

颜色只用于人工定位，不能替代 Excel 中的原始值、最终值和校验状态。

## 安全边界

- 导出前后输入 PDF 的 SHA-256 必须一致；
- 两种 PDF 都是另存副本，绝不覆盖输入；
- 核对版 PDF 只使用已有的页面坐标，不根据文字内容猜测坐标；
- Excel 不嵌入 500–1000 页的整页图片，避免文件异常膨胀；
- 无来源坐标的交易仍显示在 Excel，但必须显式标为 `unlocated`，交由人工查看 `Source Index` 或原 PDF。

## 人工验收

1. 在输出文件夹打开 `*.comparison.pdf`，查看框和 `T####` 编号；
2. 在 `*.xlsx` 的 `Transactions` 中按 `comparison_id` 找同一编号；
3. 核对 Excel 的日期、金额、余额与框内原 PDF 文字；
4. 黄色和红色行优先打开 `*.review.xlsx` 处理；
5. 只有页面、数字、合计和异常均已检查后，才把结果交付使用。
