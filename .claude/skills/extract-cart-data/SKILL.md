---
name: extract-cart-data
description: Extract source-supported CAR-T entities and experimental evidence from papers, patents, database records, or internal documents into this project's YAML-defined JSONL format, with per-document data.jsonl, optional error_log.jsonl, and reasoning.md.
---

# CAR-T Document Extraction

## Workflow and execution scope

1. Read all current `docs/Schema/*.yaml` files. Active YAML fields, types, descriptions, and enums are authoritative; commented-out definitions are not fields.
2. Read the supplied document, including relevant tables, figures, captions, and supplied supplements. Follow the source-reading rules below.
3. Extract distinct entities, combinations, and evidence; cross-check values and relationships against the source.
4. Write `data.jsonl`, `reasoning.md`, and any current-run `error_log.jsonl` in the document's output folder, normalize measurements, and complete the checks below. Apply explicit runner overrides as described under Output.

Use one agent by default. Do not spawn subagents or launch other agent processes unless the user or runner explicitly enables them (`--subagent true`). When enabled, follow the Independent extraction and cross-check section below. Subagents assigned a draft must not delegate further. Report whether independent cross-checking actually completed; ordinary single-agent extraction is not an incomplete run.

Follow the output-folder and runner-override rules below. Work only on the assigned document and its output files; `--workers` is managed by the runner, not by this skill. Keep rendered pages, downloads, and drafts in a unique temporary directory per run, or in a separate scratch subdirectory of the runner's private staging workspace when its override requires all writes there. Do not consult previous extraction outputs to fill source gaps. Do not modify schemas, code, or other documents' results during extraction.

## Independent extraction and cross-check

Apply only when the user or runner explicitly enables subagents.

The main agent coordinates this workflow. Subagents perform only their assigned extraction; they must not spawn further subagents or write the final output files.

Respect user-specified subagent models. When model selection is supported and the user has not specified a model, prefer an available lower-cost model capable of full-document extraction, including the required context length, image understanding, and tool use. Apply the choice through actual tool parameters or agent configuration, not merely the task description. If model selection is unavailable, use the inherited model without claiming a different model was used.

1. **Independent drafts.** Start two subagents, each tasked with extracting the entire supplied document. Give both the source path, this skill, the schema paths, and separate temporary output locations. Each must read the full skill, all schema files, and the document. Neither may see the other draft or previous extraction results before submitting its own draft.
2. **Source support.** Each subagent returns candidate rows and exceptions, with supporting passages and source locations for populated values and relationships, including page, table, figure, or panel identifiers where available. Keep review material separately from the candidate JSONL; do not add fields to the schema.
3. **Compare.** After both drafts are complete, the main agent aligns records by source-supported entity identity, experimental group, and measurement conditions, not row order or generated UUIDs. Compare values, attribution, missing records, and cases where only one draft supplies a value.
4. **Resolve from the source.** Re-read the relevant text, tables, or images to resolve differences. Another agent's answer, agreement, or majority vote is not evidence. Also spot-check agreeing results against the source, especially numerical values and entity relationships. Apply the existing missing-information and conflicting-evidence rules when the source remains ambiguous or contradictory; a disagreement between drafts alone is not a conflict in the source.
5. **Final output.** Only the main agent writes final `data.jsonl`, optional `error_log.jsonl`, and `reasoning.md`. Reconcile identifiers and references across accepted records, and log exceptions according to the final decisions rather than copying both draft logs. Follow the existing output format and completion checks.

If subagents are unavailable or two independent drafts cannot be completed, finish using the single-agent workflow and disclose the limitation in the final response. State whether the cross-check was completed; do not claim it occurred when it did not. Record this execution status in `reasoning.md`, keeping it out of the extracted rows and source-exception sidecar.

## Read the source

Supported input formats match `scripts/run_extraction_agent.py`: `.pdf`, `.xml`, `.nxml`, `.md`, and `.markdown`. Report other formats as unsupported.

- **XML/NXML:** read the article content directly. Exclude reference lists and acknowledgments from extraction; do not discard the entire `<back>` section because it may contain relevant appendices or supplement links.
- **Recover missing source material for every input format**, including BigQuery Markdown/text exports. If a relevant figure, table, supplement, or sequence listing is referenced but absent, look locally first, then attempt online retrieval with available network tools (or permitted shell HTTP downloads) before treating it as unavailable. This is part of source reading, not an optional follow-up for the user.
  - Resolve the article using its DOI/PMCID, or the patent using its publication number including kind code. Prefer the article's PMC/publisher page and linked supplements, or the exact patent publication's Google Patents/patent-office page and linked PDF, drawings, and sequence listing. Verify identity and version before using retrieved content; do not substitute a related paper, patent-family member, or granted version for the supplied publication.
  - Follow actual source-page or document links; do not guess asset URLs. For XML/NXML, inspect figure labels, captions, `<graphic xlink:href>`, tables, and supplementary-material links; relative filenames need resolution against the source. For text exports without links, locate the matching source page first. Retrieve only material relevant to extraction, reusing downloads within the run.
  - Retrieved material verified as part of the same source is eligible evidence under this skill. Search snippets, captions alone, and unrelated external knowledge cannot substitute for the missing content.
  - Actually inspect downloaded images or rendered PDF pages with an image-viewing tool, together with captions and panel labels. Read tables with row/column headers, units, and footnotes; read sequence listings with their SEQ ID identifiers. A successful download alone does not establish readable evidence. Extract explicitly labeled numbers only; do not estimate values from bar heights or curves. SD/SEM must be supported by text or legends.
  - Keep downloads in temporary locations, or within the runner's private staging directory when required by its output override. Record source-page and asset URLs, retrieval date, inspected figure/table/page/SEQ ID locations, and affected fields in `reasoning.md`; retain the original source identity in evidence rows and use schema-supported citation fields for locations.
  - Stop once the needed material is obtained or the source and a relevant alternative route are exhausted. Use bounded request timeouts, respect the run budget and access controls, and do not repeatedly retry a blocked endpoint. If network/image tools are unavailable, access fails, identity is uncertain, or content remains unreadable, retain readable evidence and log only the unresolved affected fields/records using existing exception categories. State attempted URLs and failure reasons in `reasoning.md`; do not report successfully recovered content as still missing.
- **PDFs:** when text extraction loses table alignment, image content, or sequence characters, render and inspect the affected pages. A caption or URL alone does not count as viewing a figure.
- Read measurements with their row/column headers, units, footnotes, groups, and panels. Extract explicitly labeled numbers, not estimates from bar heights or curves. Identify SD/SEM from the source, not the appearance of error bars.
- Verify suspected OCR errors against the page image. If content remains unreadable or image tools are unavailable, preserve readable information and log only the affected fields or records.

## Decide what to extract

**Entities:** A is the Binder, B is the CAR backbone, and C is the manufacturing process. Follow their YAML definitions to separate entity properties from measured evidence. Extract all source-supported records, not just one record per document.

Create an entity only when the document treats it as part of its own claims, embodiments, experiments, results, or actually tested controls, with meaningful data or relationships beyond a name. Ignore background mentions, prior-art surveys, citations, and generic example lists without creating placeholder rows or exceptions.

Reuse an entity across its experiments when identity is clear. Do not merge entities merely because names are similar. Preserve source names and identifiers; broader entity deduplication happens downstream.

**Combinations:** create an ABC combination only when the source links all three components to the same experimental system or product. Extract identifiable components when A, B, or C is missing, but do not fabricate a complete combination.

**Evidence:** for the same ABC combination, keep multiple readouts from the same experiment under the same conditions in one evidence row, even when they appear in different figure panels. Separate rows when the combination, experiment, or conditions differ, including groups, target cells, E:T ratios, time points, or stimulation rounds. Shared figure numbers or entity IDs alone do not establish the same experiment. Repeated descriptions of the same experiment are not independent evidence. Never transfer a measurement between entities or experiments without explicit source support.

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

### One folder per document

Use `data/normalised/<source-stem>/` for each document. If the user overrides the output root, keep the same per-document folder structure under that root. Each document has at most three final files:

```text
<source-stem>/
  data.jsonl
  error_log.jsonl   # only when exceptions occur
  reasoning.md
```

Always write `data.jsonl` and `reasoning.md`, including when extraction returns no records. Keep independent drafts, review material, downloads, rendered pages, and other scratch artifacts outside the final document folder. When the runner requires writes inside its private staging workspace, keep scratch material separate from the three final files there; only the final artifacts are published. Do not create additional per-document reports, alternate data formats, or timestamped copies. On a rerun, refresh these final artifacts for the current extraction; do not append new data or reasoning to a previous run. Start the exception log fresh for this run, removing a previous generated `error_log.jsonl` if the current run has no exceptions.

### Reasoning summary

Write `reasoning.md` as a concise evidence and decision summary, not a transcript of private internal reasoning. Include:

* the source identity and content inspected, including any unavailable content;
* consequential extraction decisions: entity and experimental-group attribution, schema mappings, record grouping, exclusions, and handling of ambiguity or conflicts;
* source locations supporting those decisions (page, section, table, figure, or panel), linked to table, row number, and field name when applicable; final record IDs may also be used when they will not be rewritten by the runner;
* whether the independent cross-check and final validation completed, plus any limitations.

Summarize final decisions and their supporting evidence; do not reproduce step-by-step internal deliberation or the agents' private reasoning. Ordinary extraction rationale belongs here. Actual exceptions still belong in `error_log.jsonl`; this summary does not replace the exception log or add fields to the schema.

### Runner overrides

When the runner supplies a private staging directory, write `data.jsonl`, `reasoning.md`, and optional `error_log.jsonl` directly there; do not add a `<source-stem>/` subfolder. The runner publishes them into the final per-document folder. Follow its explicit overrides for write locations, identifiers, nullable-field completion, and normalization. If it assigns final UUIDs, reference records in `reasoning.md` by table, row number, and field name so references survive publication. If it performs normalization, preserve source values and leave conversion to the runner; report validation or normalization as pending until verified rather than claiming the runner has already completed them. The UUID and normalization instructions below apply when those steps have not been delegated to the runner.

### Data file

Write `data.jsonl` in the resolved output folder as UTF-8 JSONL with readable Unicode, one object per line containing exactly `table` and `data`. Build `data` from the active YAML fields rather than copying a fixed example.

Unless the runner overrides identifier generation, generate each new primary identifier with Python's standard-library `uuid.uuid4()`. Reuse it consistently in foreign keys. Write rows in this order:

1. **Entities:** `binder`, `car`, `manufacturing`; include their generated primary keys and all defined non-key fields.
2. **Combinations:** `abc_combination_db1`; include its primary key, the three existing entity IDs, and its defined non-key fields.
3. **Evidence:** include the generated `record_id`, all active shared fields, and all three dotted foreign-key columns. For single-entity evidence, populate only that entity's foreign key, leave the others `null`, and include only that owner's dotted measurement fields. For combination evidence, populate all three foreign keys and include source-supported readouts in their appropriate active schema fields, including dotted measurement fields. Keep readouts from the same experiment and conditions together as specified above; filling all three foreign keys does not exclude measurement fields. Do not invent a generic result field when none exists in the schema.

The dotted names are literal keys: `car.exhaustion_phenotype` and `manufacturing.exhaustion_phenotype` are distinct columns. Each referenced entity must appear earlier in the file. Evidence needs source provenance; omit and log a row lacking a required source identifier.

Unless normalization is delegated to the runner, after writing normalize measurement units from the repository root using the project environment and the actual output path:

```bash
PYTHONPATH=src /home/zzz010122/anaconda3/envs/fosun/bin/python -m cart_db.measurements <output-jsonl-path>
```

This command updates supported units in place and preserves `raw`; do not undo its conversions. It is unit normalization, not full schema validation. If it fails, report the failure and do not claim successful normalization.

## Exceptions

Write only current-run exceptions to `error_log.jsonl` in the document's output folder (or directly in the runner's staging directory). Each entry has these keys:

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

Handle errors at the smallest valid scope. For an entirely empty or unreadable document, write an empty `data.jsonl`, a document-level exception, and a `reasoning.md` summary of the limitation. Preserve usable records when only part of the source is affected. Do not log ordinary unreported optional fields, excluded background, reasoning, unsupported unit conversions, or information outside the schema. Keep exceptions and execution status out of data rows.

## Completion checks

Before reporting completion:

- Cross-check values, entity links, groups, and source locations; resolve discrepancies from the document rather than another model's answer.
- Parse each output line and check field names, shapes, types, enums, missing values, and required provenance against active YAML. Check identifiers against the active execution contract (UUIDs by default or document-local labels under the runner override), foreign-key targets, and row order. YAML `check`/`pattern` rules are not automatically enforced by every project parser; do not claim validation merely because JSON parses.
- Verify normalization succeeded (or was explicitly delegated to the runner), and only current-run exceptions remain. Verify the final document folder contains only `data.jsonl`, `reasoning.md`, and optional `error_log.jsonl`; scratch files in runner staging must remain separate from these publishable artifacts. Check that the non-empty reasoning summary reflects the final records and actual cross-check/validation status.
- Count written rows by table and exceptions from the files. Report counts, unresolved failures, and whether extraction was single-agent or independently cross-checked.
