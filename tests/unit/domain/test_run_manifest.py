from dataclasses import FrozenInstanceError

import pytest

from bankocr.domain.run_manifest import RunManifest


def _manifest():
    return RunManifest(
        app_version="0.1.0",
        project_schema_version="1",
        ocr_engine="rapidocr",
        ocr_model_id="pp-ocrv6-small",
        model_sha256="a" * 64,
        execution_provider="CPUExecutionProvider",
        preprocess_profile="bank-default-v1",
        parser_version="parser-v1",
        template_version="template-pack-v1",
        validation_rules_version="rules-v1",
        exporter_version="exporter-v1",
    )


def test_run_manifest_serializes_all_reproducibility_pins():
    manifest = _manifest()

    values = manifest.to_dict()

    assert values["ocr_model_id"] == "pp-ocrv6-small"
    assert values["model_sha256"] == "a" * 64
    assert values["validation_rules_version"] == "rules-v1"
    assert set(values) == {
        "app_version",
        "project_schema_version",
        "ocr_engine",
        "ocr_model_id",
        "model_sha256",
        "execution_provider",
        "preprocess_profile",
        "parser_version",
        "template_version",
        "validation_rules_version",
        "exporter_version",
    }


def test_run_manifest_is_immutable_after_run_creation():
    manifest = _manifest()

    with pytest.raises(FrozenInstanceError):
        manifest.ocr_model_id = "another-model"
