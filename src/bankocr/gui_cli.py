"""Entry point for the optional PySide6 processing window."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from bankocr.domain.run_manifest import RunManifest
from bankocr.gui.error_reporting import user_error_summary, write_error_log
from bankocr.gui.runtime import (
    missing_runtime_resources,
    resolve_gui_paths,
    windows_documents_dir,
)
from bankocr.ocr.model_pack import ModelPack
from bankocr.ocr.rapidocr_backend import RapidOCRBackend
from bankocr.pipeline.processor import DocumentProcessor
from bankocr.pipeline.run_service import ProjectRunService
from bankocr.storage.project_store import ProjectStore
from bankocr.task.document_queue import PdfTask, PdfTaskExecutor, PdfTaskQueue, ResourcePolicy
from bankocr.gui.main_window import run_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BankOCR Windows offline processing UI")
    parser.add_argument("--project-db", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--model-manifest", type=Path)
    parser.add_argument("--template-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--font-file", type=Path)
    parser.add_argument("--low-resource", action="store_true")
    return parser


def show_startup_error(message: str) -> None:
    """Display a blocking Chinese startup error before the main window exists."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    application = QApplication.instance() or QApplication([])
    QMessageBox.critical(None, "BankOCR 启动失败", message)


def _default_log_root() -> Path:
    return windows_documents_dir() / "BankOCR" / "\u65e5\u5fd7"


def _safe_write_startup_log(
    log_root: Path,
    *,
    error: BaseException | None = None,
    message: str | None = None,
) -> None:
    try:
        write_error_log(
            log_root=log_root,
            context="startup",
            error=error,
            message=message,
        )
    except Exception:
        return


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store: ProjectStore | None = None
    paths = None
    try:
        paths = resolve_gui_paths(
            project_db=args.project_db,
            model_dir=args.model_dir,
            model_manifest=args.model_manifest,
            template_dir=args.template_dir,
            output_dir=args.output_dir,
            font_file=args.font_file,
        )
        for directory in (paths.data_root, paths.output_root, paths.log_root):
            directory.mkdir(parents=True, exist_ok=True)

        missing = list(missing_runtime_resources(paths))
        if paths.font_file is None:
            missing.append("CJK \u5b57\u4f53")
        if missing:
            message = (
                "\u542f\u52a8\u5931\u8d25\uff1a\u7f3a\u5c11\u8fd0\u884c\u8d44\u6e90\uff1a"
                f"{', '.join(missing)}\u3002\u8bf7\u91cd\u65b0\u5b89\u88c5 BankOCR \u6216\u68c0\u67e5\u8bca\u65ad\u53c2\u6570\u3002"
            )
            _safe_write_startup_log(paths.log_root, message=message)
            show_startup_error(f"{message}\n\u65e5\u5fd7\u4f4d\u7f6e\uff1a{paths.log_root}")
            return 2

        model_pack = ModelPack.from_manifest(paths.model_dir, paths.model_manifest)
        backend = RapidOCRBackend(model_pack=model_pack)
        processor = DocumentProcessor(backend=backend, template_dir=paths.template_dir)
        store = ProjectStore(paths.project_db)
        service = ProjectRunService(store, processor)
        policy = ResourcePolicy.low_resource() if args.low_resource else ResourcePolicy()
        queue = PdfTaskQueue(PdfTaskExecutor(service, policy=policy))

        def task_factory(source: Path) -> PdfTask:
            project_id = store.create_project(source.stem, source)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            manifest = RunManifest(
                app_version="0.1.0",
                project_schema_version=str(store.SCHEMA_VERSION),
                ocr_engine=backend.engine_id,
                ocr_model_id="PP-OCRv6-small",
                model_sha256=model_pack.fingerprint,
                execution_provider="CPUExecutionProvider",
                preprocess_profile="default-v1",
                parser_version="parser-v1",
                template_version="templates-v1",
                validation_rules_version="validation-v1",
                exporter_version="export-v1",
                template_fingerprint=processor.template_fingerprint,
                validation_rules_fingerprint=processor.validation_rules_fingerprint,
            )
            return PdfTask(
                source,
                project_id,
                manifest,
                output_dir=paths.output_root / f"{source.stem}-{timestamp}-{project_id}",
                font_file=paths.font_file,
            )

        return run_main(
            queue,
            task_factory,
            output_root=paths.output_root,
            log_root=paths.log_root,
        )
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        log_root = paths.log_root if paths is not None else _default_log_root()
        _safe_write_startup_log(log_root, error=error)
        show_startup_error(
            user_error_summary(error, log_root=log_root, startup=True)
        )
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
