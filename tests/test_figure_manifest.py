"""Exercise artifact provenance independently of any model or database connection."""
import json

import pytest

from cart_db.artifacts import artifact_manifest, checksum, verify_artifacts
from cart_db.ingest_schema import contract_hash


@pytest.fixture
def bundle(tmp_path):
    """Create a source and a valid no-figure document bundle for manifest checks."""
    source = tmp_path / "source.xml"
    source.write_text("<article><body>No figures.</body></article>")
    output = tmp_path / "output"
    output.mkdir()
    # Required text artifacts remain independent of the presence of result images.
    for name in ("data.jsonl", "original.jsonl", "reasoning.md", "figures.jsonl"):
        (output / name).write_text("")
    (output / "img").mkdir()
    return source, output


def save_manifest(output, manifest):
    """Persist the exact manifest a runner would publish after validation."""
    (output / "source_manifest.json").write_text(json.dumps(manifest))


def test_manifest_tracks_no_figure_bundle_and_source(bundle):
    """Even a document with zero figures must explicitly carry the figure contract."""
    source, output = bundle
    manifest = artifact_manifest(output, source, agent="fixture", model="offline")
    assert manifest["figure_contract_version"] == 1
    assert set(manifest["artifacts"]) == {"data.jsonl", "original.jsonl", "reasoning.md", "figures.jsonl"}
    save_manifest(output, manifest)
    assert verify_artifacts(output, source) == manifest
    source.write_text("different source")
    with pytest.raises(ValueError, match="原文或字段"):
        verify_artifacts(output, source)


def test_legacy_bundle_only_allowed_for_explicit_backfill(bundle):
    """An old provenance record is sufficient for backfill but not normal reuse."""
    source, output = bundle
    manifest = dict(source_sha256=checksum(source), schema_hash=contract_hash(),
                    artifacts={name: checksum(output / name)
                               for name in ("data.jsonl", "original.jsonl", "reasoning.md")})
    save_manifest(output, manifest)
    assert verify_artifacts(output, source, require_figures=False) == manifest
    with pytest.raises(ValueError, match="--figures-only"):
        verify_artifacts(output, source)


def test_modified_text_cannot_be_backfilled(bundle):
    """Figure-only mode cannot silently bless modifications to structured evidence."""
    source, output = bundle
    save_manifest(output, artifact_manifest(output, source))
    (output / "original.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="校验和"):
        verify_artifacts(output, source, require_figures=False)


def test_manifest_rejects_traversal_members(bundle):
    """Only exact bundle members may be read; manifest-supplied paths are untrusted."""
    source, output = bundle
    manifest = artifact_manifest(output, source)
    manifest["artifacts"]["../source.xml"] = checksum(source)
    save_manifest(output, manifest)
    with pytest.raises(ValueError, match="清单"):
        verify_artifacts(output, source)


@pytest.mark.parametrize("member", ["reasoning.md", "img"])
def test_manifest_rejects_linked_artifacts(bundle, member):
    """Links must not allow an output bundle to depend on files outside its directory."""
    source, output = bundle
    destination = output / member
    # The image attachment is a directory; other required attachments are ordinary files.
    if destination.is_dir():
        destination.rmdir()
        destination.symlink_to(source.parent, target_is_directory=True)
    else:
        destination.unlink()
        destination.symlink_to(source)
    with pytest.raises(ValueError):
        artifact_manifest(output, source)


def test_manifest_covers_images_even_when_inventory_is_consistently_rewritten(bundle):
    """Changing an image and its inventory hash still invalidates the outer manifest."""
    import fitz
    from cart_db.figures import export_figures

    _, output = bundle
    source = output.parent / "source.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(20, 20, 100, 100), color=(1, 0, 0))
    document.save(source)
    document.close()
    record = dict(figure_id="fig-001", label="Figure 1", caption="Synthetic chart",
                  category="plot", panels=[], status="extracted", path="img/fig-001.png",
                  page=1, bbox=[10, 10, 110, 110])
    (output / "figures.jsonl").write_text(json.dumps(record) + "\n")
    export_figures(source, output, dpi=100)
    manifest = artifact_manifest(output, source)
    assert "img/fig-001.png" in manifest["artifacts"]
    save_manifest(output, manifest)
    assert verify_artifacts(output, source) == manifest
    # A fresh rendering is internally consistent but no longer matches the published bytes.
    export_figures(source, output, dpi=200)
    with pytest.raises(ValueError, match="校验和"):
        verify_artifacts(output, source, require_figures=False)
