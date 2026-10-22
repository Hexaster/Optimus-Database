"""Validation and bundle-integrity checks for animal-result figure copies."""
import json

import pytest

from cart_db.agent_output import OutputError
from cart_db.animal_figures import validate_animal_figures
from cart_db.artifacts import artifact_manifest, verify_artifacts


def _data(tmp_path, *, animal=True):
    path = tmp_path / "data.jsonl"
    data = {"animal.efficacy_outcomes": [{"endpoint": "tumor volume"}] if animal else None}
    path.write_text(json.dumps({"table": "evidence", "data": data}) + "\n", encoding="utf-8")
    return path


def _figures(tmp_path, data_path, *, name="Figure_2.png", row=1):
    directory = tmp_path / "animal_figures"
    directory.mkdir(exist_ok=True)
    (directory / name).write_bytes(b"synthetic source figure")
    (directory / "manifest.json").write_text(json.dumps({"figures": [{
        "file": name, "source_locator": "Figure 2A-C", "evidence_rows": [row],
    }]}), encoding="utf-8")
    return directory


def test_validates_animal_figure_manifest_and_row_link(tmp_path):
    data = _data(tmp_path)
    directory = _figures(tmp_path, data)
    assert [p.name for p in validate_animal_figures(directory, data)] == [
        "manifest.json", "Figure_2.png",
    ]


def test_rejects_manifest_link_to_non_animal_row(tmp_path):
    data = _data(tmp_path, animal=False)
    directory = _figures(tmp_path, data)
    with pytest.raises(OutputError, match="without animal results"):
        validate_animal_figures(directory, data)


def test_rejects_path_traversal_in_manifest(tmp_path):
    data = _data(tmp_path)
    directory = _figures(tmp_path, data)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["figures"][0]["file"] = "../outside.png"
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(OutputError, match="unsafe or unsupported"):
        validate_animal_figures(directory, data)


def test_animal_figure_files_are_included_in_bundle_checksums(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("No figure inventory items for this test.", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    evidence = {"table": "evidence", "data": {
        "animal.efficacy_outcomes": [{"endpoint": "tumor volume"}],
    }}
    (output / "data.jsonl").write_text(json.dumps(evidence) + "\n", encoding="utf-8")
    (output / "original.jsonl").write_bytes((output / "data.jsonl").read_bytes())
    (output / "reasoning.md").write_text("animal result copied", encoding="utf-8")
    (output / "figures.jsonl").write_text("", encoding="utf-8")
    (output / "img").mkdir()
    directory = _figures(output, output / "data.jsonl")
    manifest = artifact_manifest(output, source)
    assert "animal_figures/Figure_2.png" in manifest["artifacts"]
    assert "animal_figures/manifest.json" in manifest["artifacts"]
    (output / "source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_artifacts(output, source) == manifest
    (directory / "Figure_2.png").write_bytes(b"changed figure")
    with pytest.raises(ValueError, match="校验和不匹配"):
        verify_artifacts(output, source)
