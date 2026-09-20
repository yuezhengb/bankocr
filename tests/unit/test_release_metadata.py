import json
from pathlib import Path

from scripts import create_release_metadata


def test_release_metadata_contains_pinned_components_and_file_hashes(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "requirements-lock.txt").write_text("rapidocr==3.9.0\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    output = tmp_path / "sbom.json"
    monkeypatch.setattr("sys.argv", ["create_release_metadata.py", "--root", str(tmp_path), "--output", str(output)])

    assert create_release_metadata.main() == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["components"] == [{"name": "rapidocr", "type": "library", "version": "3.9.0"}]
    assert "README.md" in payload["files"]
    assert payload["files_sha256"]
