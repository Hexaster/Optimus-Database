# Image extraction subagent

The extraction coordinator delegates this task to **one dedicated image subagent** for each document, alongside structured-data extraction. This delegation is independent of `--subagent`, which controls two independent structured-data drafts. The image subagent must not delegate further. If the backend cannot launch subagents or inspect images, fail explicitly instead of reporting an image review that did not happen.

The coordinator supplies the source path and private output directory. Only the image subagent writes `figures.jsonl` and `img/`; scratch material goes in `scratch/`. Do not modify structured records, schemas, or other documents. The coordinator waits for this task and checks its inventory against the source before publication. Native subagent calls share the enclosing document timeout and, where supported by the backend, its budget; do not launch independent paid CLI processes.

## Scope and review

1. Inspect every page or source section and all supplied figure assets. Inventory result figures, including charts, flow-cytometry plots, microscopy, blots, and supplementary results. Include results even when no active database field can hold them.
2. Save complete figures with every panel, axis, legend, label, and annotation. Do not split panels by default. Exclude logos/decorations and purely explanatory schematics; record excluded numbered figures and the reason. Preserve uncertain result figures and explain the uncertainty.
3. Transcribe the source label and caption without inventing missing text. Keep figure references such as S1 separate from main figure 1. Record unavailable referenced figures/supplements with the precise reason; do not turn missing images into a successful extraction or invent a crop.
4. **Acquire images through an official source API first, then use PDF as fallback**, even when a local PDF is already supplied. Follow the Image acquisition priority section of `.claude/skills/extract-cart-data/SKILL.md`. Resolve original/highest-quality assets through documented API routes or returned metadata links; verify source identity, figure label, caption, and panels. Prefer complete original-resolution or vector assets, not thumbnails. API images are not automatically better: compare completeness and readability, preserve native resolution, and record the chosen source, URL, retrieval date, checksum, and fallback reason. If API retrieval fails or produces an unusable/inferior image, retrieve or open the matching PDF, inspect rendered pages, select the full figure rectangle in PDF page coordinates (points, top-left origin, one-based page), then render the rectangle. Embedded-image extraction alone is insufficient: plots can be vector drawings or fragmented images. If one figure spans pages, use distinct IDs/parts with the same source label and explain the split.
5. For XML/Markdown, inspect supplied asset references and use verified source identifiers to retrieve missing images through the API-first, PDF-fallback procedure above. Reuse verified local copies of API assets. Preserve the original reference and retrieval provenance. Missing local drawings or a remote URL alone are not reasons to stop. Mark a figure `unavailable` only after applicable API and PDF routes fail, or explain the access/tool limitation that prevented a route. Keep downloads in the private workspace and never fabricate a source reference to satisfy validation.
6. Open every exported crop and compare it to the source. Correct clipped legends/axes, unrelated surrounding content, wrong page/label associations, or unreadable renderings. Upsampling cannot recover missing information.
7. Report extracted/unavailable/excluded counts and review limitations to the coordinator. An empty inventory is valid only after inspecting the document and finding no figures; create an empty `img/` directory too.

This task preserves visual evidence. It does not introduce new chart digitization or biological calculations. Existing structured-extraction rules for source-supported values and `image_estimated_range` still apply.

The current export helper handles PDF crops and source-referenced local XML/Markdown assets; it does not perform API retrieval. Its local-file restrictions are not a prohibition on API acquisition. Do not claim a remotely acquired asset was exported or validated by this helper unless its actual provenance is supported.

## Inventory contract

Write UTF-8 JSONL, one object per figure:

```json
{"figure_id":"fig-001","label":"Figure 1","caption":"Exact source caption","panels":["A","B"],"category":"experimental_results","status":"extracted","page":3,"bbox":[40,50,560,420],"path":"img/fig-001.png"}
```

- `figure_id`: unique safe filename identifier, e.g. `fig-001`, `fig-s001`.
- `label`, `caption`, `category`: source label/caption and descriptive category; empty caption only when genuinely absent.
- `panels`: source panel labels, or an empty list.
- `status`: `extracted`, `unavailable`, or `excluded`.
- PDF exports require `page` and `bbox`; local XML/Markdown exports require `source_asset`.
- Exported `path` is exactly `img/<figure_id>.png`. The exporter fills `sha256` and image dimensions.
- `issue`: required explanation for unavailable/excluded items and any uncertainty.
- Unavailable/excluded entries have no image path or checksum. Never create placeholder images.

Use the project Python environment, with `PYTHONPATH=src`:

```bash
# Render page previews into private scratch space, then inspect them visually.
python scripts/extract_figures.py render --source SOURCE.pdf --output-dir OUTPUT/scratch/pages

# After authoring OUTPUT/figures.jsonl, export all specified crops/assets.
python scripts/extract_figures.py export --source SOURCE.pdf --output-dir OUTPUT

# Check image contents, paths, hashes, and source coordinates.
python scripts/extract_figures.py validate --source SOURCE.pdf --output-dir OUTPUT
```

Run `--help` for the exact supported options. Use source page dimensions, not preview pixel coordinates, for `bbox`. The default export resolution is 200 DPI. All final images go in the document's single `img/` folder; previews must remain under scratch.

## Coordinator integration and backfills

The runner requires a valid inventory and image set before publishing structured results. It publishes `img/` as a complete replacement so stale crops cannot survive a rerun. The source manifest records the figure contract version and checksums for metadata and every image. Database ingestion saves `figures.jsonl` and the manifest as context; image bytes remain on disk. Preserve the output directory when moving or backing up the database.

Use figure labels/panels and relative image links in `reasoning.md` to connect evidence to crops, with table, physical JSONL line number and field where supported. Do not infer a record association solely from a shared figure label. Standalone image backfills leave the original reasoning and scientific records unchanged; the figure inventory supplies source-level attribution.

To add images to an existing, checksummed extraction without repeating structured extraction:

```bash
python scripts/run_extraction_agent.py --file SOURCE.pdf --out-dir EXISTING_OUTPUT_ROOT --figures-only
```

Backfills require an existing source manifest with matching source, schema and artifact hashes. Older unmanifested results need a full `--force` extraction because their provenance cannot be verified. Run database import separately after a backfill. Existing complete outputs are skipped only after validating their manifest and images; old outputs without figures request a backfill explicitly.
