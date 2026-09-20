from dataclasses import replace
from pathlib import Path
import re

import pytest

from bankocr import gui_cli
from bankocr.gui.runtime import GuiRuntimePaths


def _runtime_paths(tmp_path: Path) -> GuiRuntimePaths:
    resource_root = tmp_path / "resources"
    data_root = tmp_path / "data"
    return GuiRuntimePaths(
        resource_root=resource_root,
        data_root=data_root,
        output_root=data_root / "output",
        project_db=data_root / "projects" / "project.sqlite3",
        log_root=data_root / "logs",
        model_dir=resource_root / "models",
        model_manifest=resource_root / "models" / "manifest.json",
        template_dir=resource_root / "templates" / "known",
        font_file=resource_root / "fonts" / "msyh.ttc",
    )


def _install_pipeline_doubles(monkeypatch, calls: dict[str, object]) -> None:
    class FakeModelPack:
        fingerprint = "f" * 64

    class FakeBackend:
        engine_id = "fake-ocr"

        def __init__(self, *, model_pack) -> None:
            calls["backend_model_pack"] = model_pack

    class FakeProcessor:
        template_fingerprint = "a" * 64
        validation_rules_fingerprint = "b" * 64

        def __init__(self, *, backend, template_dir) -> None:
            calls["processor_backend"] = backend
            calls["processor_template_dir"] = template_dir

    class FakeStore:
        SCHEMA_VERSION = 6

        def __init__(self, path) -> None:
            calls["project_db"] = path

        def create_project(self, name, path) -> int:
            calls["project"] = (name, path)
            return 73

        def close(self) -> None:
            calls["store_closed"] = True

    class FakeQueue:
        def __init__(self, executor) -> None:
            calls["queue_executor"] = executor

    def fake_from_manifest(model_dir, manifest):
        calls["model_pack_paths"] = (model_dir, manifest)
        return FakeModelPack()

    monkeypatch.setattr(gui_cli.ModelPack, "from_manifest", fake_from_manifest)
    monkeypatch.setattr(gui_cli, "RapidOCRBackend", FakeBackend)
    monkeypatch.setattr(gui_cli, "DocumentProcessor", FakeProcessor)
    monkeypatch.setattr(gui_cli, "ProjectStore", FakeStore)
    monkeypatch.setattr(gui_cli, "PdfTaskQueue", FakeQueue)


def test_build_parser_accepts_no_arguments() -> None:
    args = gui_cli.build_parser().parse_args([])

    assert args.project_db is None
    assert args.model_dir is None
    assert args.model_manifest is None
    assert args.template_dir is None
    assert args.output_dir is None
    assert args.font_file is None
    assert args.low_resource is False


def test_main_uses_resolved_paths_for_the_existing_processing_pipeline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _runtime_paths(tmp_path)
    source = tmp_path / "statement.pdf"
    calls: dict[str, object] = {}
    _install_pipeline_doubles(monkeypatch, calls)

    def fake_run_main(queue, task_factory, *, output_root=None, log_root=None) -> int:
        calls["run_main_queue"] = queue
        calls["task"] = task_factory(source)
        calls["output_root"] = output_root
        calls["log_root"] = log_root
        return 0

    monkeypatch.setattr(gui_cli, "resolve_gui_paths", lambda **kwargs: paths)
    monkeypatch.setattr(gui_cli, "missing_runtime_resources", lambda _: ())
    monkeypatch.setattr(gui_cli, "run_main", fake_run_main)
    monkeypatch.setattr(gui_cli, "show_startup_error", lambda _: None)

    assert gui_cli.main([]) == 0

    assert calls["model_pack_paths"] == (paths.model_dir, paths.model_manifest)
    assert calls["backend_model_pack"].fingerprint == "f" * 64
    assert calls["processor_template_dir"] == paths.template_dir
    assert calls["project_db"] == paths.project_db
    task = calls["task"]
    assert task.source == source
    assert task.project_id == 73
    assert task.font_file == paths.font_file
    assert task.output_dir.parent == paths.output_root
    assert re.fullmatch(r"statement-\d{8}-\d{6}-73", task.output_dir.name)
    assert calls["output_root"] == paths.output_root
    assert calls["store_closed"] is True
    assert paths.data_root.is_dir()
    assert paths.output_root.is_dir()
    assert paths.log_root.is_dir()


def test_main_passes_all_path_overrides_to_resolution_and_uses_output_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    default_paths = _runtime_paths(tmp_path)
    source = tmp_path / "statement.pdf"
    overrides = {
        "project_db": tmp_path / "override" / "project.sqlite3",
        "model_dir": tmp_path / "override" / "models",
        "model_manifest": tmp_path / "override" / "models" / "manifest.json",
        "template_dir": tmp_path / "override" / "templates" / "known",
        "output_dir": tmp_path / "override" / "output",
        "font_file": tmp_path / "override" / "fonts" / "cjk.ttc",
    }
    calls: dict[str, object] = {}
    _install_pipeline_doubles(monkeypatch, calls)

    def fake_resolve_gui_paths(**kwargs):
        calls["resolve_kwargs"] = kwargs
        return replace(
            default_paths,
            project_db=kwargs["project_db"],
            model_dir=kwargs["model_dir"],
            model_manifest=kwargs["model_manifest"],
            template_dir=kwargs["template_dir"],
            output_root=kwargs["output_dir"],
            font_file=kwargs["font_file"],
        )

    def fake_run_main(queue, task_factory, *, output_root=None, log_root=None) -> int:
        calls["task"] = task_factory(source)
        calls["output_root"] = output_root
        calls["log_root"] = log_root
        return 0

    monkeypatch.setattr(gui_cli, "resolve_gui_paths", fake_resolve_gui_paths)
    monkeypatch.setattr(gui_cli, "missing_runtime_resources", lambda _: ())
    monkeypatch.setattr(gui_cli, "run_main", fake_run_main)
    monkeypatch.setattr(gui_cli, "show_startup_error", lambda _: None)

    assert gui_cli.main(
        [
            "--project-db", str(overrides["project_db"]),
            "--model-dir", str(overrides["model_dir"]),
            "--model-manifest", str(overrides["model_manifest"]),
            "--template-dir", str(overrides["template_dir"]),
            "--output-dir", str(overrides["output_dir"]),
            "--font-file", str(overrides["font_file"]),
            "--low-resource",
        ]
    ) == 0

    assert calls["resolve_kwargs"] == overrides
    assert calls["project_db"] == overrides["project_db"]
    assert calls["processor_template_dir"] == overrides["template_dir"]
    assert calls["model_pack_paths"] == (
        overrides["model_dir"],
        overrides["model_manifest"],
    )
    assert calls["task"].output_dir.parent == overrides["output_dir"]
    assert calls["task"].font_file == overrides["font_file"]
    assert calls["output_root"] == overrides["output_dir"]


def test_main_reports_missing_model_pack_and_returns_2(tmp_path: Path, monkeypatch) -> None:
    paths = _runtime_paths(tmp_path)
    errors: list[str] = []

    monkeypatch.setattr(gui_cli, "resolve_gui_paths", lambda **kwargs: paths)
    monkeypatch.setattr(gui_cli, "missing_runtime_resources", lambda _: ("models",))
    monkeypatch.setattr(gui_cli, "show_startup_error", errors.append)
    monkeypatch.setattr(gui_cli.ModelPack, "from_manifest", lambda *_: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(gui_cli, "RapidOCRBackend", lambda **_: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(gui_cli, "DocumentProcessor", lambda **_: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(gui_cli, "ProjectStore", lambda *_: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(gui_cli, "PdfTaskQueue", lambda *_: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(gui_cli, "run_main", lambda *_: (_ for _ in ()).throw(AssertionError()))

    assert gui_cli.main([]) == 2

    assert len(errors) == 1
    assert "models" in errors[0]


@pytest.mark.parametrize("error", [FileNotFoundError("missing onnx"), ValueError("invalid model manifest")])
def test_main_reports_model_pack_startup_errors(tmp_path: Path, monkeypatch, error: Exception) -> None:
    paths = _runtime_paths(tmp_path)
    errors: list[str] = []

    monkeypatch.setattr(gui_cli, "resolve_gui_paths", lambda **kwargs: paths)
    monkeypatch.setattr(gui_cli, "missing_runtime_resources", lambda _: ())
    monkeypatch.setattr(gui_cli, "show_startup_error", errors.append)
    monkeypatch.setattr(gui_cli.ModelPack, "from_manifest", lambda *_: (_ for _ in ()).throw(error))

    assert gui_cli.main([]) == 2

    assert len(errors) == 1
    assert str(error) in errors[0]


def test_main_reports_template_loading_startup_errors(tmp_path: Path, monkeypatch) -> None:
    paths = _runtime_paths(tmp_path)
    errors: list[str] = []

    monkeypatch.setattr(gui_cli, "resolve_gui_paths", lambda **kwargs: paths)
    monkeypatch.setattr(gui_cli, "missing_runtime_resources", lambda _: ())
    monkeypatch.setattr(gui_cli, "show_startup_error", errors.append)
    monkeypatch.setattr(gui_cli.ModelPack, "from_manifest", lambda *_: type("Pack", (), {"fingerprint": "f" * 64})())
    monkeypatch.setattr(gui_cli, "RapidOCRBackend", lambda **_: type("Backend", (), {"engine_id": "fake-ocr"})())
    monkeypatch.setattr(gui_cli, "DocumentProcessor", lambda **_: (_ for _ in ()).throw(ValueError("invalid template manifest")))

    assert gui_cli.main([]) == 2

    assert len(errors) == 1
    assert "invalid template manifest" in errors[0]


def test_main_requires_a_cjk_font_before_loading_ocr(tmp_path: Path, monkeypatch) -> None:
    paths = replace(_runtime_paths(tmp_path), font_file=None)
    errors: list[str] = []

    monkeypatch.setattr(gui_cli, "resolve_gui_paths", lambda **kwargs: paths)
    monkeypatch.setattr(gui_cli, "missing_runtime_resources", lambda _: ())
    monkeypatch.setattr(gui_cli, "show_startup_error", errors.append)
    monkeypatch.setattr(gui_cli.ModelPack, "from_manifest", lambda *_: (_ for _ in ()).throw(AssertionError()))

    assert gui_cli.main([]) == 2

    assert len(errors) == 1
    assert "CJK" in errors[0]


def test_main_closes_the_project_store_if_queue_startup_fails(tmp_path: Path, monkeypatch) -> None:
    paths = _runtime_paths(tmp_path)
    calls: dict[str, object] = {}

    class FakeStore:
        SCHEMA_VERSION = 6

        def __init__(self, path) -> None:
            calls["project_db"] = path

        def close(self) -> None:
            calls["store_closed"] = True

    monkeypatch.setattr(gui_cli, "resolve_gui_paths", lambda **kwargs: paths)
    monkeypatch.setattr(gui_cli, "missing_runtime_resources", lambda _: ())
    monkeypatch.setattr(gui_cli.ModelPack, "from_manifest", lambda *_: type("Pack", (), {"fingerprint": "f" * 64})())
    monkeypatch.setattr(gui_cli, "RapidOCRBackend", lambda **_: type("Backend", (), {"engine_id": "fake-ocr"})())
    monkeypatch.setattr(gui_cli, "DocumentProcessor", lambda **_: type("Processor", (), {"template_fingerprint": "a" * 64, "validation_rules_fingerprint": "b" * 64})())
    monkeypatch.setattr(gui_cli, "ProjectStore", FakeStore)
    monkeypatch.setattr(gui_cli, "PdfTaskQueue", lambda *_: (_ for _ in ()).throw(RuntimeError("queue startup failed")))
    errors: list[str] = []
    monkeypatch.setattr(gui_cli, "show_startup_error", errors.append)

    assert gui_cli.main([]) == 2

    assert calls["store_closed"] is True
    assert errors and "queue startup failed" in errors[0]


def test_main_logs_startup_exception_without_blocking_original_error(tmp_path: Path, monkeypatch) -> None:
    paths = _runtime_paths(tmp_path)
    errors: list[str] = []
    startup_error = FileNotFoundError("missing onnx")

    monkeypatch.setattr(gui_cli, "resolve_gui_paths", lambda **kwargs: paths)
    monkeypatch.setattr(gui_cli, "missing_runtime_resources", lambda _: ())
    monkeypatch.setattr(gui_cli, "show_startup_error", errors.append)
    monkeypatch.setattr(gui_cli.ModelPack, "from_manifest", lambda *_: (_ for _ in ()).throw(startup_error))

    assert gui_cli.main([]) == 2

    assert errors and "\u542f\u52a8\u5931\u8d25" in errors[0]
    logs = list(paths.log_root.glob("*.log"))
    assert logs
    content = logs[0].read_text(encoding="utf-8")
    assert "FileNotFoundError" in content
    assert "missing onnx" in content


def test_main_continues_when_startup_logging_fails(tmp_path: Path, monkeypatch) -> None:
    paths = _runtime_paths(tmp_path)
    errors: list[str] = []

    monkeypatch.setattr(gui_cli, "resolve_gui_paths", lambda **kwargs: paths)
    monkeypatch.setattr(gui_cli, "missing_runtime_resources", lambda _: ())
    monkeypatch.setattr(gui_cli, "show_startup_error", errors.append)
    monkeypatch.setattr(gui_cli, "write_error_log", lambda **_kwargs: (_ for _ in ()).throw(PermissionError("log denied")))
    monkeypatch.setattr(gui_cli.ModelPack, "from_manifest", lambda *_: (_ for _ in ()).throw(PermissionError("model denied")))

    assert gui_cli.main([]) == 2

    assert errors and "\u542f\u52a8\u5931\u8d25" in errors[0]
