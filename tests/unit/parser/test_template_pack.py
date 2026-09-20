import json

from bankocr.parser.template_pack import TemplatePack


def test_template_pack_loads_declarative_templates_and_checks_manifest(tmp_path) -> None:
    template_dir = tmp_path / "known"
    template_dir.mkdir()
    template = {
        "template_id": "generic-test-v1",
        "version": "1",
        "header_tokens": ["记账日期", "余额"],
        "columns": [
            {"name": "accounting_date", "left_ratio": 0.0, "right_ratio": 0.5},
            {"name": "balance", "left_ratio": 0.5, "right_ratio": 1.0},
        ],
        "required_fields": ["accounting_date", "balance"],
        "row_strategy": "anchor_date",
    }
    path = template_dir / "generic-test-v1.json"
    path.write_text(json.dumps(template, ensure_ascii=False), encoding="utf-8")

    pack = TemplatePack.from_directory(template_dir)
    assert pack.template_ids == ("generic-test-v1",)
    assert pack.templates[0].columns[1].name == "balance"

    manifest = tmp_path / "manifest.json"
    pack.write_manifest(manifest)
    loaded = TemplatePack.from_directory(template_dir, manifest_path=manifest)
    assert loaded.fingerprint == pack.fingerprint


def test_template_pack_rejects_a_tampered_template(tmp_path) -> None:
    template_dir = tmp_path / "known"
    template_dir.mkdir()
    path = template_dir / "template.json"
    path.write_text(
        json.dumps(
            {
                "template_id": "test-v1",
                "version": "1",
                "header_tokens": ["日期", "余额"],
                "columns": [
                    {"name": "date", "left_ratio": 0.0, "right_ratio": 0.5},
                    {"name": "balance", "left_ratio": 0.5, "right_ratio": 1.0},
                ],
                "required_fields": ["date", "balance"],
                "row_strategy": "anchor_date",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pack = TemplatePack.from_directory(template_dir)
    manifest = tmp_path / "manifest.json"
    pack.write_manifest(manifest)
    path.write_text(path.read_text(encoding="utf-8").replace("余额", "账户余额"), encoding="utf-8")

    try:
        TemplatePack.from_directory(template_dir, manifest_path=manifest)
    except ValueError as exc:
        assert "fingerprint" in str(exc) or "checksum" in str(exc)
    else:
        raise AssertionError("expected template pack verification to fail")
