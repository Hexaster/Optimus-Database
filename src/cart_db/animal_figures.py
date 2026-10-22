"""Validate copied animal-result figures and their evidence-row manifest."""
from __future__ import annotations

import json
from pathlib import Path

from .agent_output import OutputError


ANIMAL_FIGURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".svg", ".pdf"}
ANIMAL_RESULT_FIELDS = (
    "animal.efficacy_outcomes", "animal.safety_outcomes", "animal.cell_kinetics",
)


def validate_animal_figures(directory: str | Path, data_path: str | Path) -> list[Path]:
    """Check copied source figures and one-based links to animal evidence rows.

    Paths are restricted to direct files in the dedicated folder; symlinks, nested
    directories, unsupported types, unlinked files and non-animal row references fail.
    """
    directory, data_path = Path(directory), Path(data_path)
    if directory.is_symlink() or not directory.is_dir():
        raise OutputError("animal_figures must be a regular directory")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise OutputError("animal_figures/manifest.json is required")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        data_lines = data_path.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in data_lines if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OutputError(f"animal figure manifest or data is unreadable: {exc}") from exc
    figures = manifest.get("figures") if isinstance(manifest, dict) else None
    if not isinstance(figures, list) or not figures:
        raise OutputError("animal_figures/manifest.json must contain a non-empty figures list")

    referenced: set[str] = set()
    filenames: set[str] = set()
    for index, item in enumerate(figures, 1):
        if not isinstance(item, dict):
            raise OutputError(f"animal figure manifest entry {index} must be an object")
        name = item.get("file")
        locator = item.get("source_locator")
        evidence_rows = item.get("evidence_rows")
        if (not isinstance(name, str) or not name or "\\" in name or Path(name).name != name
                or Path(name).suffix.lower() not in ANIMAL_FIGURE_EXTENSIONS):
            raise OutputError(f"animal figure manifest entry {index} has an unsafe or unsupported file")
        if name in filenames:
            raise OutputError(f"animal figure manifest entry {index} repeats a filename")
        filenames.add(name)
        figure_path = directory / name
        if figure_path.is_symlink() or not figure_path.is_file() or figure_path.stat().st_size == 0:
            raise OutputError(f"animal figure file is missing, empty, or a symlink: {name}")
        if not isinstance(locator, str) or not locator.strip():
            raise OutputError(f"animal figure manifest entry {index} needs source_locator")
        if not isinstance(evidence_rows, list) or not evidence_rows:
            raise OutputError(f"animal figure manifest entry {index} needs evidence_rows")
        for row_number in evidence_rows:
            if type(row_number) is not int or row_number < 1 or row_number > len(rows):
                raise OutputError(f"animal figure manifest entry {index} has an invalid evidence row")
            row = rows[row_number - 1]
            if (not isinstance(row, dict) or row.get("table") != "evidence"
                    or not isinstance(row.get("data"), dict)
                    or not any(row["data"].get(field) is not None for field in ANIMAL_RESULT_FIELDS)):
                raise OutputError(f"animal figure manifest entry {index} points to a row without animal results")
            referenced.add(name)

    files: set[str] = set()
    for path in directory.iterdir():
        if path.name == "manifest.json":
            continue
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ANIMAL_FIGURE_EXTENSIONS:
            raise OutputError(f"unexpected file in animal_figures: {path.name}")
        files.add(path.name)
    if referenced != files:
        raise OutputError("animal figure manifest must reference every copied figure exactly by filename")
    return [manifest_path, *(directory / name for name in sorted(files))]
