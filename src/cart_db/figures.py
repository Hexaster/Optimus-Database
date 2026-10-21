"""Render complete result figures and validate their document-local evidence index.

The image agent chooses regions and transcribes captions. This module only handles
local files, rendering and integrity checks; it never guesses scientific content.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import pymupdf as fitz


# IDs also become filenames, so restrict them to a portable single path component.
FIGURE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
STATUSES = {"extracted", "unavailable", "excluded"}


def _open_pdf(source: Path) -> fitz.Document:
    """Normalize malformed/missing PDF errors to the validator's public exception type."""
    try:
        return fitz.open(source)
    except Exception as exc:
        raise ValueError(f"Cannot read source PDF: {source}") from exc


def _local_path(root: Path, relative: str) -> Path:
    """Resolve a relative artifact path without allowing traversal or symlink escape."""
    candidate = Path(relative)
    # Absolute paths and parent traversal are never document-local artifacts.
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in relative:
        raise ValueError(f"Unsafe relative path: {relative!r}")
    resolved = (root / candidate).resolve()
    # Resolution also catches an otherwise innocent-looking escaping symlink.
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes document directory: {relative!r}")
    return resolved


def _read_inventory(directory: Path) -> list[dict]:
    """Read JSONL strictly so truncated or malformed agent output cannot publish."""
    path = _local_path(directory, "figures.jsonl")
    # A missing inventory differs from an explicit, valid empty inventory.
    if not path.is_file():
        raise ValueError(f"Missing figure inventory: {path}")
    records = []
    # Preserve row order as the agent's document-reading order.
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        # Blank lines have no record semantics and can be ignored.
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid figure JSON on line {number}: {exc}") from exc
        # JSON scalars and lists are not inventory records.
        if not isinstance(record, dict):
            raise ValueError(f"Figure line {number} must be an object")
        records.append(record)
    return records


def _check_record(record: dict, seen: set[str]) -> None:
    """Validate shared metadata before interpreting a source or output path."""
    identifier = record.get("figure_id")
    # Stable unique IDs prevent one figure overwriting another on export.
    if not isinstance(identifier, str) or not FIGURE_ID.fullmatch(identifier) or identifier in seen:
        raise ValueError(f"Invalid or duplicate figure_id: {identifier!r}")
    seen.add(identifier)
    # Text metadata remains required even when an empty caption is appropriate.
    for field in ("label", "caption", "category"):
        if not isinstance(record.get(field), str):
            raise ValueError(f"{identifier}: {field} must be text")
    panels = record.get("panels")
    # Keep explicit panel labels without trying to infer panel boundaries.
    if not isinstance(panels, list) or any(not isinstance(panel, str) for panel in panels):
        raise ValueError(f"{identifier}: panels must be a list of strings")
    status = record.get("status")
    # Only extracted records are allowed to advertise a local image.
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError(f"{identifier}: unsupported status {status!r}")
    if status == "extracted":
        if record.get("path") != f"img/{identifier}.png":
            raise ValueError(f"{identifier}: path must be img/{identifier}.png")
    else:
        if record.get("path") or record.get("sha256"):
            raise ValueError(f"{identifier}: non-extracted figure cannot claim an image")
        if not isinstance(record.get("issue"), str) or not record["issue"].strip():
            raise ValueError(f"{identifier}: explain unavailable/excluded status in issue")


def _pdf_region(record: dict, document: fitz.Document) -> tuple[fitz.Page, fitz.Rect]:
    """Check the agent's 1-based page and crop in the page's displayed PDF points."""
    page_number = record.get("page")
    # Booleans are Python integers but are not sensible page numbers.
    if type(page_number) is not int or not 1 <= page_number <= len(document):
        raise ValueError(f"{record['figure_id']}: page is outside the source PDF")
    box = record.get("bbox")
    # Reject NaN, infinity, reversed coordinates and zero-area crops.
    if (not isinstance(box, list) or len(box) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in box)):
        raise ValueError(f"{record['figure_id']}: bbox must contain four finite PDF coordinates")
    page = document[page_number - 1]
    rect = fitz.Rect(box)
    if rect.is_empty or rect.is_infinite or not page.rect.contains(rect):
        raise ValueError(f"{record['figure_id']}: bbox lies outside the page or has no area")
    return page, rect


def _source_asset(source: Path, record: dict) -> Path:
    """Resolve a referenced local XML/Markdown asset without downloading remote URLs."""
    reference = record.get("source_asset")
    if not isinstance(reference, str) or not reference:
        raise ValueError(f"{record['figure_id']}: source_asset is required")
    parsed = urlsplit(reference)
    # Network URLs, data URLs and file URLs are intentionally not fetched.
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError(f"{record['figure_id']}: source_asset must be a plain local reference")
    # Require evidence that the asset reference occurs in the submitted source.
    if reference not in source.read_text(encoding="utf-8"):
        raise ValueError(f"{record['figure_id']}: asset reference does not occur in the source")
    asset = _local_path(source.parent, unquote(parsed.path))
    if not asset.is_file():
        raise ValueError(f"{record['figure_id']}: referenced source asset is missing: {reference}")
    return asset


def validate_figures(directory: str | Path, source: str | Path | None = None) -> list[dict]:
    """Validate inventory, local PNGs, SHA256 digests and optional source crop bounds."""
    directory = Path(directory)
    records = _read_inventory(directory)
    image_dir = _local_path(directory, "img")
    if not image_dir.is_dir():
        raise ValueError(f"Missing image directory: {image_dir}")
    source_path = Path(source).resolve() if source is not None else None
    document = _open_pdf(source_path) if source_path and source_path.suffix.lower() == ".pdf" else None
    seen: set[str] = set()
    expected: set[Path] = set()
    try:
        # Check each record independently; one invalid image blocks publication.
        for record in records:
            _check_record(record, seen)
            if record["status"] != "extracted":
                continue
            path = _local_path(directory, record["path"])
            expected.add(path)
            if not path.is_file():
                raise ValueError(f"Missing figure image: {path}")
            if not path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"Figure must be a PNG image: {path}")
            try:
                pixmap = fitz.Pixmap(str(path))
                if pixmap.width < 1 or pixmap.height < 1:
                    raise ValueError("Empty image")
            except Exception as exc:
                raise ValueError(f"Unreadable figure image: {path}") from exc
            # Older inventories may omit dimensions; exported inventories always record them.
            for field, actual_size in (("width", pixmap.width), ("height", pixmap.height)):
                if field in record and record[field] != actual_size:
                    raise ValueError(f"Figure {field} does not match image: {path}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if record.get("sha256") != digest:
                raise ValueError(f"Figure checksum mismatch: {path}")
            if document is not None:
                _pdf_region(record, document)
            elif source_path is not None:
                asset = _source_asset(source_path, record)
                if record.get("source_asset_sha256") != hashlib.sha256(asset.read_bytes()).hexdigest():
                    raise ValueError(f"Source asset checksum mismatch: {asset}")
        # Unindexed images would otherwise be silently published without provenance.
        actual = {path.resolve() for path in image_dir.rglob("*") if path.is_file()}
        if actual != expected:
            raise ValueError("img directory contains files absent from figures.jsonl")
    finally:
        # PDF handles must close even when a record fails validation.
        if document is not None:
            document.close()
    return records


def export_figures(source: str | Path, directory: str | Path, *, dpi: int = 200) -> list[dict]:
    """Export reviewed inventory regions/assets to PNG and write their content hashes."""
    source = Path(source).resolve()
    directory = Path(directory)
    if dpi < 72 or dpi > 600:
        raise ValueError("Export DPI must be between 72 and 600")
    records = _read_inventory(directory)
    _local_path(directory, "img").mkdir(parents=True, exist_ok=True)
    document = _open_pdf(source) if source.suffix.lower() == ".pdf" else None
    seen: set[str] = set()
    try:
        # Validate identity before exporting so duplicate records cannot overwrite.
        for record in records:
            _check_record(record, seen)
        for record in records:
            if record["status"] != "extracted":
                continue
            path = _local_path(directory, record["path"])
            if document is not None:
                page, rect = _pdf_region(record, document)
                pixmap = page.get_pixmap(dpi=dpi, clip=rect, alpha=False)
            else:
                asset = _source_asset(source, record)
                record["source_asset_sha256"] = hashlib.sha256(asset.read_bytes()).hexdigest()
                # Convert local vector/image assets through a PDF to preserve whole figures.
                with fitz.open(asset) as asset_document:
                    if len(asset_document) != 1:
                        raise ValueError(f"{record['figure_id']}: source asset must have one page")
                    with fitz.open("pdf", asset_document.convert_to_pdf()) as converted:
                        pixmap = converted[0].get_pixmap(dpi=dpi, alpha=False)
            pixmap.save(str(path))
            record["width"] = pixmap.width
            record["height"] = pixmap.height
            record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    finally:
        if document is not None:
            document.close()
    inventory = _local_path(directory, "figures.jsonl")
    inventory.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
    return validate_figures(directory, source)


def render_pages(source: str | Path, directory: str | Path, pages: list[int] | None = None, *, dpi: int = 100) -> list[dict]:
    """Render numbered PDF pages and geometry for an image agent's visual inspection."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if dpi < 36 or dpi > 300:
        raise ValueError("Inspection DPI must be between 36 and 300")
    metadata = []
    with fitz.open(source) as document:
        selected = list(range(1, len(document) + 1)) if pages is None else pages
        # Explicit page numbers permit inspecting only relevant portions of long papers.
        for number in selected:
            if type(number) is not int or not 1 <= number <= len(document):
                raise ValueError(f"Page outside source document: {number}")
            page = document[number - 1]
            filename = f"page-{number:04d}.png"
            page.get_pixmap(dpi=dpi, alpha=False).save(str(_local_path(directory, filename)))
            metadata.append({"page": number, "path": filename, "width_points": page.rect.width,
                             "height_points": page.rect.height, "dpi": dpi,
                             "text": page.get_text()})
    _local_path(directory, "pages.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata
