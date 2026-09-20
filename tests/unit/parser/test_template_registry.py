import json

from bankocr.parser.template_pack import TemplatePack
from bankocr.parser.template_registry import TemplateRegistry


def _pack(root, template_id: str, right_name: str):
    known = root / "known"
    known.mkdir(parents=True)
    (known / "template.json").write_text(
        json.dumps(
            {
                "template_id": template_id,
                "version": "1",
                "header_tokens": ["日期", "余额"],
                "columns": [
                    {"name": "date", "left_ratio": 0.0, "right_ratio": 0.5},
                    {"name": right_name, "left_ratio": 0.5, "right_ratio": 1.0},
                ],
                "required_fields": ["date", right_name],
                "row_strategy": "anchor_date",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pack = TemplatePack.from_directory(known)
    manifest = root / "manifest.json"
    pack.write_manifest(manifest)
    return known, manifest, pack.fingerprint


def test_template_registry_activates_new_pack_and_rolls_back(tmp_path) -> None:
    first_dir, first_manifest, first_fingerprint = _pack(tmp_path / "first", "first", "balance")
    second_dir, second_manifest, second_fingerprint = _pack(tmp_path / "second", "second", "online_balance")
    registry = TemplateRegistry(tmp_path / "registry")

    registry.install(first_dir, first_manifest, activate=True)
    registry.install(second_dir, second_manifest, activate=True)

    assert registry.current().fingerprint == second_fingerprint
    assert registry.previous().fingerprint == first_fingerprint
    rolled_back = registry.rollback()
    assert rolled_back.fingerprint == first_fingerprint
    assert registry.current().template_dir.is_dir()
