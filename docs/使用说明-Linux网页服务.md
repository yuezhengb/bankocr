# Linux web service (self-host)

`bankocr-server` is an optional loopback HTTP UI for uploading a PDF and downloading results. It is **not** bound to any company domain. Replace example hostnames with your own.

## Default listen address

The server binds `127.0.0.1:18081` unless you pass `--host` / `--port`. That is intentional: bank statements should not be exposed on a public interface without TLS and access control.

Linux install uses [`requirements-linux-server.txt`](../requirements-linux-server.txt). Some distributions need a system OpenCV library such as `libGL` / `mesa-libGL`.

## Local run

```bash
python -m venv .venv312
.venv312/bin/python -m pip install -r requirements-linux-server.txt
.venv312/bin/python -m pip install -e .
export PYTHONPATH=src
.venv312/bin/python -m bankocr.server \
  --host 127.0.0.1 \
  --port 18081 \
  --work-dir ./data \
  --model-dir ./models \
  --model-manifest ./models/manifest.json \
  --template-dir ./templates/known \
  --font-file ./fonts/msyh.ttc \
  --dpi 150
```

Open `http://127.0.0.1:18081`. Health check: `curl http://127.0.0.1:18081/healthz`.

A sample systemd unit lives at [`deploy/systemd/bankocr-server.service`](../deploy/systemd/bankocr-server.service) (`WorkingDirectory=/opt/bankocr-server`). Adjust user, paths, and Python interpreter for your host.

## SSH tunnel (optional)

If the process runs on a remote machine but should stay off the public internet:

```bash
ssh -L 18081:127.0.0.1:18081 user@your-server.example
```

Keep that session open, then browse `http://127.0.0.1:18081`.

## HTTPS reverse proxy (optional)

Example Nginx site files:

- [`deploy/nginx/ocr.example.com.conf`](../deploy/nginx/ocr.example.com.conf)
- [`deploy/nginx/ocr.example.com-acme.conf`](../deploy/nginx/ocr.example.com-acme.conf)

Replace `ocr.example.com` with your hostname. Create an htpasswd file **outside git**:

```bash
sudo htpasswd -c /etc/nginx/.htpasswd-bankocr example-user
```

Terminate TLS at Nginx (Let's Encrypt or another certificate). Proxy to `http://127.0.0.1:18081` and do not forward `Authorization` to the app. The BankOCR process should remain loopback-only.

Do not commit passwords, htpasswd files, private keys, or real certificate material.

## Using the page

1. Choose a bank-statement PDF and start processing.
2. Wait while the job is queued or running. The server processes **one PDF at a time**.
3. When complete, prefer **Download all results ZIP**. Individual files remain available.
4. The ZIP contains generated results only — not the original PDF, SQLite project, or temp files.

Result groups:

- **Direct use:** structured `.xlsx`
- **Compare with PDF:** layout Excel, comparison PDF, searchable PDF
- **Human review:** `.review.xlsx`
- **Processing record:** summary and export manifest

Default upload limit is 100 MB. The original PDF is never overwritten.

## 简体中文摘要

服务默认只监听本机 `127.0.0.1:18081`。需要远程使用时用 SSH 隧道；需要公网 HTTPS 时在前面加 Nginx，并把示例域名 `ocr.example.com` 换成你自己的域名。密码、证书私钥和真实流水 PDF 都不要提交到 Git。
