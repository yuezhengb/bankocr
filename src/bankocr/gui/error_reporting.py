"""User-facing GUI error summaries and best-effort local logs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import traceback


def write_error_log(
    *,
    log_root: Path | None,
    context: str,
    error: BaseException | None = None,
    message: str | None = None,
    task_id: str | None = None,
    source: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> Path | None:
    """Append a UTF-8 error record; never raise if logging itself fails."""

    if log_root is None:
        return None
    try:
        log_root.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        path = log_root / f"bankocr-{now:%Y%m%d}.log"
        lines = [
            "=" * 72,
            f"time: {now.isoformat(timespec='seconds')}",
            f"context: {context}",
        ]
        if task_id is not None:
            lines.append(f"task_id: {task_id}")
        if source is not None:
            lines.append(f"source: {source}")
        if output_dir is not None:
            lines.append(f"output_dir: {output_dir}")
        if error is not None:
            lines.append(f"exception_type: {type(error).__name__}")
            lines.append("traceback:")
            lines.extend(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
        elif message is not None:
            lines.append("message:")
            lines.append(message)
        else:
            lines.append("message: <empty>")
        path.write_text(
            (path.read_text(encoding="utf-8") if path.exists() else "")
            + "\n".join(lines)
            + "\n",
            encoding="utf-8",
        )
        return path
    except Exception:
        return None


def user_error_summary(
    error: BaseException | str,
    *,
    source: Path | str | None = None,
    output_dir: Path | str | None = None,
    log_root: Path | str | None = None,
    startup: bool = False,
) -> str:
    """Return a concise Chinese message suitable for ordinary employees."""

    log_hint = f" 日志位置：{log_root}" if log_root is not None else ""
    if isinstance(error, str):
        base = "处理失败：请查看日志或联系管理员。"
        return base + log_hint

    filename = source or getattr(error, "filename", None)
    if startup:
        detail = str(error)
        suffix = f"（{detail}）" if detail else ""
        return (
            "启动失败：程序包不完整或配置无效，请重新安装 BankOCR 或检查诊断参数。"
            f"{suffix}{log_hint}"
        )
    if isinstance(error, FileNotFoundError):
        target = f"：{filename}" if filename is not None else ""
        return f"无法读取文件{target}。请确认文件存在且可以打开。{log_hint}"
    if isinstance(error, PermissionError):
        error_filename = getattr(error, "filename", None)
        if error_filename is not None and source is not None:
            try:
                if Path(error_filename).resolve() == Path(source).resolve():
                    target = f"：{source}"
                    return f"无法读取文件{target}。请确认有读取权限。{log_hint}"
            except OSError:
                pass
        if output_dir is not None:
            return f"无法保存结果：{output_dir}。请确认输出目录有写入权限。{log_hint}"
        target = f"：{filename}" if filename is not None else ""
        return f"无法读取文件{target}。请确认有读取权限。{log_hint}"
    if isinstance(error, OSError) and output_dir is not None:
        return f"无法保存结果：{output_dir}。请确认磁盘空间和写入权限。{log_hint}"
    return f"处理失败：请查看日志或联系管理员。{log_hint}"
