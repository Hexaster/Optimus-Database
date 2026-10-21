"""Checksum and validate one document's structured-data and figure output bundle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .ingest_schema import contract_hash


# Hash a source or artifact in bounded chunks for safe extraction-resume checks.
def checksum(path):
    result = hashlib.sha256()
    # Close the file reliably, including when reading or writing raises an error.
    with Path(path).open("rb") as source:
        # Hash chunks until EOF so large source files do not need to fit in memory.
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


# These are the only text attachments belonging to a resumable extraction bundle.
_REQUIRED_ARTIFACTS = {"data.jsonl", "original.jsonl", "reasoning.md"}
_OPTIONAL_ARTIFACTS = {"error_log.jsonl"}
_LEGACY_SCHEMA_HASH = "fb64398a5ef997932fcf2a6b795040a050054f717bc0479de176cdc799656d9a"


def _artifact_names(directory, source, *, require_figures):
    """List validated bundle members without following links outside the output directory."""
    directory = Path(directory)
    names = set(_REQUIRED_ARTIFACTS)
    # Optional diagnostics participate in checksums whenever they are present.
    for name in _OPTIONAL_ARTIFACTS:
        if (directory / name).exists() or (directory / name).is_symlink():
            names.add(name)
    # Figure metadata and images form one contract; a partial figure bundle is never reusable.
    if require_figures:
        names.add("figures.jsonl")
        image_dir = directory / "img"
        # Reject directory links and nested content rather than hashing external or hidden assets.
        if image_dir.is_symlink() or not image_dir.is_dir():
            raise ValueError("图片目录缺失或不是独立目录；请用 --figures-only 补充图片")
        for image in image_dir.iterdir():
            if image.is_symlink() or not image.is_file() or image.suffix.lower() != ".png":
                raise ValueError(f"图片目录包含不支持的文件：{image.name}")
            names.add("img/" + image.name)
    # Every declared artifact must be an ordinary file within this output bundle.
    for name in names:
        member = directory / name
        if member.is_symlink() or not member.is_file():
            raise ValueError(f"提取产物缺失或使用了符号链接：{name}")
    # Validate references only after the complete file set has passed local path checks.
    if require_figures:
        from .figures import validate_figures
        validate_figures(directory, source=source)
    return names


def artifact_manifest(directory, source, agent=None, model=None):
    """Build checksums for validated structured data and the complete figure bundle.

    The caller writes this manifest only after ensuring the source did not change
    during extraction. Image bytes stay on disk; their hashes travel with metadata.
    """
    directory, source = Path(directory), Path(source)
    names = _artifact_names(directory, source, require_figures=True)
    return dict(source_path=str(source.resolve()), source_sha256=checksum(source),
                schema_hash=contract_hash(), agent=agent, model=model,
                figure_contract_version=1,
                artifacts={name: checksum(directory / name) for name in sorted(names)})


def verify_artifacts(directory, source, require_figures=True):
    """Verify source/schema provenance, artifact membership, and each saved checksum.

    Legacy structured outputs can be read with require_figures=False for a
    figure-only backfill. Normal resume requires the new figure contract.
    """
    directory, source = Path(directory), Path(source)
    manifest_path = directory / "source_manifest.json"
    # Outputs without a source manifest cannot establish their provenance for backfill or resume.
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("已有 JSONL 缺少原文校验记录，不能自动认定来源；请用 --force 重新提取")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Preserve the existing single historical schema exception, without accepting arbitrary hashes.
    if (not isinstance(manifest, dict)
            or manifest.get("source_sha256") != checksum(source)
            or manifest.get("schema_hash") not in (contract_hash(), _LEGACY_SCHEMA_HASH)):
        raise ValueError("原文或字段定义已经变化；请用 --force 重新提取")
    figure_version = manifest.get("figure_contract_version")
    # Old results need a figure-only upgrade; no silent reuse or implicit paid rerun is allowed.
    if require_figures and figure_version != 1:
        raise ValueError("已有提取结果缺少图片产物；请用 --figures-only 补充图片，或用 --force 重新提取")
    # Unknown future formats must not be interpreted as this version's bundle structure.
    if figure_version not in (None, 1):
        raise ValueError("图片产物版本不支持；请核对提取程序版本")
    names = _artifact_names(directory, source, require_figures=figure_version == 1)
    artifacts = manifest.get("artifacts")
    # Exact membership also blocks traversal paths and undeclared image additions/removals.
    if not isinstance(artifacts, dict) or set(artifacts) != names:
        raise ValueError("提取产物清单不完整或被修改；请恢复原文件，或用 --force 重新提取")
    for name, expected in artifacts.items():
        # A changed image is as significant for provenance as changed structured evidence.
        if not isinstance(expected, str) or checksum(directory / name) != expected:
            raise ValueError(f"提取产物校验和不匹配：{name}；请恢复原文件，或用 --force 重新提取")
    return manifest


