# Self-host examples

These files are **examples**. They do not describe a production host.

- `systemd/bankocr-server.service` — loopback `bankocr-server` on `127.0.0.1:18081` under `/opt/bankocr-server`
- `nginx/ocr.example.com.conf` — HTTPS reverse proxy + HTTP basic auth in front of that process
- `nginx/ocr.example.com-acme.conf` — HTTP-only ACME challenge helper

Replace `ocr.example.com`, certificate paths, and the htpasswd path. Keep the Python process on loopback. Never commit `.htpasswd*`, TLS private keys, or `.env` files.
