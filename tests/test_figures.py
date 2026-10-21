"""Offline figure integrity tests, including PDF shapes unavailable in sample papers."""
import json
from pathlib import Path

import pymupdf as fitz
import pytest

from cart_db.figures import export_figures, render_pages, validate_figures


def inventory(directory, **overrides):
    """Write one complete figure record, overriding fields for negative cases."""
    directory.mkdir(exist_ok=True)
    row = dict(figure_id="fig-001", label="Figure 1", caption="Results", panels=["A"],
               category="line_chart", status="extracted", page=1,
               bbox=[10, 10, 190, 90], path="img/fig-001.png")
    row.update(overrides)
    (directory / "figures.jsonl").write_text(json.dumps(row) + "\n")
    return row


@pytest.fixture
def vector_pdf(tmp_path):
    """Build a pure-vector chart, which embedded-raster extraction would miss."""
    source = tmp_path / "vector.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=100)
        page.draw_line((20, 80), (180, 20), color=(0, 0, 0), width=2)
        page.insert_text((20, 40), "Result")
        doc.save(source)
    return source


def test_vector_export_and_inspection(tmp_path, vector_pdf):
    """Vector marks survive cropping and inspection exposes PDF point geometry."""
    out = tmp_path / "out"
    inventory(out)
    records = export_figures(vector_pdf, out)
    assert 500 <= records[0]["width"] <= 501
    assert records[0]["height"] > 200
    assert validate_figures(out, vector_pdf) == records
    pix = fitz.Pixmap(str(out / "img/fig-001.png"))
    assert min(pix.samples) < 100
    pages = render_pages(vector_pdf, tmp_path / "inspection", [1])
    assert pages[0]["width_points"] == 200
    assert "Result" in pages[0]["text"]


def test_scanned_raster_page(tmp_path):
    """Whole-page raster content remains visible in exported regions."""
    source = tmp_path / "scan.pdf"
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 200, 100), False)
    pix.clear_with(30)
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=100)
        page.insert_image(page.rect, stream=pix.tobytes("png"))
        doc.save(source)
    out = tmp_path / "out"
    inventory(out)
    export_figures(source, out)
    result = fitz.Pixmap(str(out / "img/fig-001.png"))
    assert max(result.samples) < 100


def test_rotated_page_uses_display_bounds(tmp_path, vector_pdf):
    """Rotated-page crops use the dimensions shown by the inspection renderer."""
    rotated = tmp_path / "rotated.pdf"
    with fitz.open(vector_pdf) as doc:
        doc[0].set_rotation(90)
        doc.save(rotated)
    out = tmp_path / "out"
    inventory(out, bbox=[0, 0, 100, 200])
    result = export_figures(rotated, out)[0]
    assert result["height"] > result["width"]


@pytest.mark.parametrize("extension,content", [("md", "![Figure](asset.png)"), ("xml", '<fig><graphic href="asset.png"/></fig>')])
def test_local_assets(tmp_path, extension, content):
    """Both supported text-source families resolve their local figure assets."""
    source = tmp_path / f"source.{extension}"
    source.write_text(content)
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 20, 10), False)
    pix.clear_with(120)
    pix.save(tmp_path / "asset.png")
    out = tmp_path / "out"
    inventory(out, source_asset="asset.png")
    assert export_figures(source, out)[0]["source_asset_sha256"]
    (tmp_path / "asset.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Source asset checksum"):
        validate_figures(out, source)


@pytest.mark.parametrize("asset", ["missing.png", "https://example.com/a.png", "../escape.png"])
def test_unavailable_assets_are_not_fetched(tmp_path, asset):
    """Missing, remote and escaping assets require an unavailable record instead."""
    source = tmp_path / "source.md"
    source.write_text(f"![Figure]({asset})")
    out = tmp_path / "out"
    inventory(out, source_asset=asset)
    with pytest.raises(ValueError):
        export_figures(source, out)


@pytest.mark.parametrize("box", [[0, 0, 500, 500], [50, 50, 10, 10], [0, 0, 0, 1], [0, 0, float("nan"), 1]])
def test_bad_crop_rejected(tmp_path, vector_pdf, box):
    """Invalid coordinates cannot silently produce partial or empty evidence."""
    out = tmp_path / "out"
    inventory(out, bbox=box)
    with pytest.raises(ValueError, match="bbox"):
        export_figures(vector_pdf, out)


def test_duplicate_and_path_rejected(tmp_path, vector_pdf):
    """Duplicate IDs and path traversal cannot overwrite arbitrary output files."""
    out = tmp_path / "out"
    row = inventory(out)
    (out / "figures.jsonl").write_text((json.dumps(row) + "\n") * 2)
    with pytest.raises(ValueError, match="duplicate"):
        export_figures(vector_pdf, out)
    inventory(out, path="../escape.png")
    with pytest.raises(ValueError, match="path"):
        export_figures(vector_pdf, out)


def test_hash_and_extra_file_rejected(tmp_path, vector_pdf):
    """Changing an image or introducing an unindexed file invalidates the bundle."""
    out = tmp_path / "out"
    inventory(out)
    records = export_figures(vector_pdf, out)
    records[0]["sha256"] = "0" * 64
    (out / "figures.jsonl").write_text(json.dumps(records[0]) + "\n")
    with pytest.raises(ValueError, match="checksum"):
        validate_figures(out)
    export_figures(vector_pdf, out)
    (out / "img/extra.txt").write_text("unindexed")
    with pytest.raises(ValueError, match="absent"):
        validate_figures(out)


def test_empty_and_unavailable_inventory(tmp_path):
    """Explicit empty and unavailable inventories remain publishable evidence states."""
    (tmp_path / "img").mkdir()
    (tmp_path / "figures.jsonl").write_text("")
    assert validate_figures(tmp_path) == []
    inventory(tmp_path, status="unavailable", path=None, issue="Asset not supplied")
    assert validate_figures(tmp_path)[0]["status"] == "unavailable"


def test_bad_source_and_missing_inventory(tmp_path):
    """Malformed input surfaces the same ValueError contract as artifact errors."""
    with pytest.raises(ValueError, match="Missing figure inventory"):
        validate_figures(tmp_path)
    inventory(tmp_path)
    (tmp_path / "img").mkdir()
    source = tmp_path / "bad.pdf"
    source.write_text("not PDF")
    with pytest.raises(ValueError, match="Cannot read source PDF"):
        validate_figures(tmp_path, source)
