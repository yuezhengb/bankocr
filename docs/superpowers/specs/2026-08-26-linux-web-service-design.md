# Linux 网页服务部署设计

## 目标

让现有 BankOCR 在 Linux VPS 上提供一个简单的网页入口：用户上传 PDF，服务器排队处理，完成后下载普通 Excel、PDF 原样图片版 Excel、人工复核 Excel、可搜索 PDF 和核对版 PDF。原有 Windows GUI、CLI 和离线导出逻辑保持不变。

## 现状和端口决策

- Target host is a small CPU-only Linux server with a few GiB of RAM.
- Choose a port that does not collide with other services already bound on the host.
- 使用 `18081`，服务仅绑定 `127.0.0.1`；用户通过 SSH 本地端口转发访问 `http://127.0.0.1:18081`。
- 不直接把包含银行流水的 HTTP 服务暴露到公网；以后如需多人访问，再增加域名、HTTPS 和登录认证。

## 方案

新增一个只使用 Python 标准库的 `bankocr.server`：

- `GET /`：中文上传页面和任务列表。
- `GET /healthz`：健康检查。
- `POST /upload`：接收一个 PDF，限制大小，生成任务编号并立即返回。
- `GET /api/jobs`、`GET /api/jobs/<id>`：查看任务状态和结果文件。
- `GET /download/<id>/<filename>`：下载白名单内的结果文件。
- 单线程后台队列：同一时间只运行一个 OCR 任务，避免 4G 内存被多个 OCR 同时占满。
- 每个任务独立目录，输入文件和输出文件隔离；文件名只保留 basename，禁止路径穿越。
- 处理核心复用现有 `bankocr.cli.main`，不复制 OCR、解析、校验和导出逻辑。
- 服务启动参数显式指定模型目录、manifest、模板目录、字体、工作目录、端口和上传大小。

## 输出和保留

每个任务目录保存原始上传 PDF、SQLite（如 CLI 需要）和所有已有导出文件；运行中的任务状态保存在服务进程内存中，导出摘要和 manifest 负责持久化处理结果。成功任务只暴露已存在且位于该任务输出目录内的文件；失败任务返回中文错误摘要，详细异常写入服务器日志。服务重启后不会恢复旧任务列表，但不会删除旧任务目录。

## 资源边界

- 默认单文件最大 100 MiB。
- 默认一次只处理一个任务，后续任务排队。
- 服务启动前检查模型、模板、字体和工作目录。
- 不在服务层自动下载模型或依赖。
- 任务目录不自动删除，便于人工取证；后续可增加保留天数清理。

## 验收标准

1. 本地测试可启动服务，上传 PDF 后能看到 `queued`、`processing`、`completed` 状态变化。
2. 完成任务返回现有全部导出文件，包括 `*.pdf-layout.xlsx`。
3. 下载接口拒绝不存在文件、路径穿越和非白名单文件。
4. 超过大小限制、非 PDF 和缺少文件时返回明确的 4xx 错误。
5. 本地真实样本通过服务处理后，工作簿页数和直接 CLI 输出一致。
6. VPS 上服务由 systemd 管理，监听 `127.0.0.1:18081`，`curl http://127.0.0.1:18081/healthz` 返回 `ok`。
7. 本地通过 SSH 隧道访问页面并完成一次上传、轮询和结果下载。

## 明确不做

- 不在本次改动中公开监听公网网卡。
- 不把 Windows GUI 搬到 Linux。
- 不在服务器上改变原始 PDF。
- 不增加第二套 OCR 或解析算法。
