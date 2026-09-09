---
name: extract-cart-data
description: Extract source-supported CAR-T entities and experimental evidence from papers, patents, database records, or internal documents into this project's YAML-defined JSONL format.
---

# CAR-T Document Extraction

## Workflow and execution scope

1. Read all current `docs/Schema/*.yaml` files. Active YAML fields, types, descriptions, and enums are authoritative; commented-out definitions are not fields.
2. Read the supplied document, including relevant tables, figures, captions, and supplied supplements. Follow the source-reading rules below.
3. Extract distinct entities, combinations, and evidence; cross-check values and relationships against the source.
4. Write the document's JSONL and any current-run exceptions, normalize measurements, and complete the checks below.

Use one agent by default. Do not spawn subagents or launch other agent processes unless the user or runner explicitly enables them (`--subagent true`). When enabled, read [the independent cross-check workflow](references/subagent-cross-check.md). Subagents assigned a draft must not delegate further. Report whether independent cross-checking actually completed; ordinary single-agent extraction is not an incomplete run.

Honor the runner's output-directory override. Otherwise use `data/normalised/`. Work only on the assigned document and its output files; `--workers` is managed by the runner, not by this skill. Use a unique temporary directory per run for rendered pages, downloaded images, and drafts so concurrent documents cannot overwrite one another. Do not consult previous extraction outputs to fill source gaps. Do not modify schemas, code, or other documents' results during extraction.

## Read the source

Supported input formats match `scripts/run_extraction_agent.py`: `.pdf`, `.xml`, `.nxml`, `.md`, and `.markdown`. Report other formats as unsupported.

- **XML/NXML:** read the article content directly. Exclude reference lists and acknowledgments from extraction; do not discard the entire `<back>` section because it may contain relevant appendices or supplement links.
- **Figures:** identify relevant figures from labels, captions, and graphic references. Use local images first. If an article image is absent, resolve it through the article's DOI, PMCID, or source page using available tools; do not guess image URLs. Retrieve only the source images needed for extraction, not unrelated literature or product information to fill gaps.
- **PDFs:** when text extraction loses table alignment, image content, or sequence characters, render and inspect the affected pages. A caption or URL alone does not count as viewing a figure.
- Read measurements with their row/column headers, units, footnotes, groups, and panels. Extract explicitly labeled numbers, not estimates from bar heights or curves. Identify SD/SEM from the source, not the appearance of error bars.
- Verify suspected OCR errors against the page image. If content remains unreadable or image tools are unavailable, preserve readable information and log only the affected fields or records.

## Decide what to extract

**Entities:** A is the Binder, B is the CAR backbone, and C is the manufacturing process. Follow their YAML definitions to separate entity properties from measured evidence. Extract all source-supported records, not just one record per document.

Create an entity only when the document treats it as part of its own claims, embodiments, experiments, results, or actually tested controls, with meaningful data or relationships beyond a name. Ignore background mentions, prior-art surveys, citations, and generic example lists without creating placeholder rows or exceptions.

Reuse an entity across its experiments when identity is clear. Do not merge entities merely because names are similar. Preserve source names and identifiers; broader entity deduplication happens downstream.

**Combinations:** create an ABC combination only when the source links all three components to the same experimental system or product. Extract identifiable components when A, B, or C is missing, but do not fabricate a complete combination.

**Evidence:** separate experiments with different groups, conditions, time points, or targets. Repeated descriptions of the same experiment are not independent evidence. Never transfer a measurement between entities or experiments without explicit source support.

Match the quantity's meaning before its format: EC50 is not Kd, viral titer is not transduction efficiency, CD107a is not target-cell killing, and clinical Cmax/AUC is not manufacturing VCN. Apply current YAML definitions for overlapping indicators and their designated storage locations. An assessment on day 10 alone does not establish a ten-day manufacturing duration.

## Values and missing information

- Extract only explicit source information or direct, unambiguous derivations allowed by the field definition. Do not fill gaps from biological expectations, product names, earlier outputs, or synthetic examples.
- Use only active schema fields and exact enum values. Map source wording to an enum only when the equivalence is unambiguous.
- Unreported or unresolved nullable fields are `null`, including lists and whole objects. Do not substitute `[]`, `{}`, `false`, zero, an empty string, or the string `"missing"`. If part of an object is reported, keep that object and set its unreported nullable members to `null`.
- Do not omit an applicable field's key. If a required member cannot be supported, omit the affected item or record at the smallest valid scope and apply the exception rules; do not fabricate a value.
- `json` with `shape: object` is one object. `shape: array` is a list, using `item_schema` for object members or `item_type` for scalar items. `string` is text, not an invented JSON structure. Scalars retain their declared types; dates use ISO 8601.
- Interpret booleans according to the field description. For sterility and mycoplasma tests, `true` means positive and `false` means negative, not pass/fail. Unknown is `null`.
- Keep descriptive values concise while preserving source terminology and necessary qualifications. Do not add your own explanations or bracketed reasoning. Source parentheses, measurement `raw`, and necessary experimental details may be retained.
- Use active condition fields for the corresponding assay. Do not emit commented-out `experimental_conditions` or invent a replacement field. Preserve context in `raw` where its field definition permits; information without a current schema destination is omitted without an exception against another field.
- `evidence_level` is assigned downstream: do not emit it, invent a score, or drop evidence because it is absent. For dates, distinguish source upload/download metadata from publication dates and the extraction date; unreported dates remain `null`.

## Measurements and sequences

For `measurement`, follow the structure and `kind` definitions at the top of `Evidence.yaml`. Even a single number is an object with `kind`, `value`, `lower`, `upper`, `error`, `unit`, and `raw`; unused members are `null`.

Preserve source values, units, statistical meaning, and denominators. Do not collapse ranges, turn mean ± SD into a range, guess SD versus SEM, or assign a pooled range to one entity. Missing units stay `null`; `preferred_unit` does not establish the source unit. Follow any field-specific ratio representation. Otherwise leave conversion to the normalization command below; unsupported conversions are not extraction exceptions.

Copy sequences exactly, removing only layout whitespace and joining blocks in unambiguous reading order. Verify unreadable or OCR-corrupted characters against the source image; never repair them from expected biology. If unresolved, leave the affected sequence field `null` and log the exception.

Do not reconstruct missing regions or infer VH/VL/linker/module boundaries without explicit or unambiguous source support. Before comparing sequences, distinguish full expression constructs, CAR proteins, fragments, and individual modules. Differences in scope alone do not establish a conflict. Use the schema's coordinate and chain-scope definitions.

## Conflicts and provenance

For conflicting measurements with clear identity and context, retain the attributable values in separate evidence rows with exact source locations and log the conflict. Do not select a preferred value or alter the source. When identity or attribution is uncertain, retain unambiguous data and leave affected nullable fields `null`; omit a record only if its identity cannot be established.

Use actual source identifiers such as DOI, PMCID, patent accession, or internal document ID. Never invent them. In `citation`, include the source reference and available page, section, table, figure, or panel location for the evidence. Do not invent page numbers. Interpret `contrary_evidence` from source-supported context, not merely from disagreement between extraction drafts.

## Output

Write `<out_dir>/<source-stem>.jsonl` as UTF-8 JSONL with readable Unicode, one object per line containing exactly `table` and `data`. Build `data` from the active YAML fields rather than copying a fixed example.

Generate each new primary identifier with Python's standard-library `uuid.uuid4()`. Reuse it consistently in foreign keys. Write rows in this order:

1. **Entities:** `binder`, `car`, `manufacturing`; include their generated primary keys and all defined non-key fields.
2. **Combinations:** `abc_combination_db1`; include its primary key, the three existing entity IDs, and its defined non-key fields.
3. **Evidence:** include the generated `record_id`, all active shared fields, and all three dotted foreign-key columns. For single-entity evidence, populate only that entity's foreign key, leave the others `null`, and include only that owner's dotted measurement fields. For combination evidence, populate all three foreign keys and include only active shared fields. Do not invent a generic result field when none exists in the schema.

The dotted names are literal keys: `car.exhaustion_phenotype` and `manufacturing.exhaustion_phenotype` are distinct columns. Each referenced entity must appear earlier in the file. Evidence needs source provenance; omit and log a row lacking a required source identifier.

On an authorized rerun, replace this document's final output and exception sidecar with current-run results; do not append to old results. If no current exceptions remain, leave no stale sidecar for this document. Do not touch other documents' outputs.

After writing, normalize measurement units from the repository root using the project environment and the actual output path:

```bash
PYTHONPATH=src /home/zzz010122/anaconda3/envs/fosun/bin/python -m cart_db.measurements <output-jsonl-path>
```

This command updates supported units in place and preserves `raw`; do not undo its conversions. It is unit normalization, not full schema validation. If it fails, report the failure and do not claim successful normalization.

## Exceptions

Write only current-run exceptions to `<out_dir>/<source-stem>.errors.jsonl`. Each entry has these keys:

| Key | Meaning |
| --- | --- |
| `source` | Source filename |
| `stage` | Stage where the problem occurred, such as `validation` |
| `record_index` | One-based candidate-record index, or `null` when not applicable |
| `field` | Affected schema field, or `null` for a record/document issue |
| `reason` | Most specific category below |
| `raw_value` | Source value involved, or `null` |
| `action` | What was actually done |

Reasons: `unreadable_source`, `ambiguous_evidence`, `invalid_enum`, `invalid_numeric_value`, `schema_mismatch`, `missing_required_provenance`, `unsupported_relationship`, `output_validation_error`.

Actions: `set_missing`, `omit_record`, `return_empty_result`, `preserve_conflicting_values`.

Handle errors at the smallest valid scope. For an entirely empty or unreadable document, write an empty main JSONL and a document-level exception. Preserve usable records when only part of the source is affected. Do not log ordinary unreported optional fields, excluded background, reasoning, unsupported unit conversions, or information outside the schema. Keep exceptions and execution status out of data rows.

## Completion checks

Before reporting completion:

- Cross-check values, entity links, groups, and source locations; resolve discrepancies from the document rather than another model's answer.
- Parse each output line and check field names, shapes, types, enums, missing values, and required provenance against active YAML. Check generated UUIDs, foreign-key targets, and row order. YAML `check`/`pattern` rules are not automatically enforced by every project parser; do not claim validation merely because JSON parses.
- Verify normalization succeeded and only current-run exceptions remain.
- Count written rows by table and exceptions from the files. Report counts, unresolved failures, and whether extraction was single-agent or independently cross-checked.
