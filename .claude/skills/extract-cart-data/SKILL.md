---
name: extract-cart-data
description: Extract source-supported CAR-T entities and experimental evidence from papers, patents, database records, or internal documents into this project's YAML-defined JSONL format, with per-document data.jsonl, optional error_log.jsonl, and reasoning.md.
---

# CAR-T Document Extraction

## Workflow and execution scope

1. Read all current `docs/Schema/*.yaml` files. Active YAML fields, types, descriptions, and enums are authoritative; commented-out definitions are not fields.
2. Read the supplied document, including relevant tables, figures, captions, and supplied supplements. Follow the source-reading rules below.
3. Build a temporary inventory of source-described experiments and independent processes, then extract their distinct entities, combinations, and evidence into active schema fields. Follow Coverage and semantic review below.
4. Return to the source to check coverage, then check attribution and meaning. Update the inventory and draft for omissions found during review.
5. Write `data.jsonl`, `reasoning.md`, and any current-run `error_log.jsonl` in the document's output folder, normalize measurements, and complete the checks below. Apply explicit runner overrides as described under Output.

Use one agent by default. Do not spawn subagents or launch other agent processes unless the user or runner explicitly enables them (`--subagent true`). When enabled, follow the Independent extraction and cross-check section below. Subagents assigned a draft must not delegate further. Report whether independent cross-checking actually completed; ordinary single-agent extraction is not an incomplete run.

Follow the output-folder and runner-override rules below. Work only on the assigned document and its output files; `--workers` is managed by the runner, not by this skill. Keep rendered pages, downloads, and drafts in a unique temporary directory per run, or in a separate scratch subdirectory of the runner's private staging workspace when its override requires all writes there. Do not consult previous extraction outputs to fill source gaps. Do not modify schemas, code, or other documents' results during extraction.

## Independent extraction and cross-check

Apply only when the user or runner explicitly enables subagents.

The main agent coordinates this workflow. Subagents perform only their assigned extraction; they must not spawn further subagents or write the final output files.

Respect user-specified subagent models. When model selection is supported and the user has not specified a model, prefer an available lower-cost model capable of full-document extraction, including the required context length, image understanding, and tool use. Apply the choice through actual tool parameters or agent configuration, not merely the task description. If model selection is unavailable, use the inherited model without claiming a different model was used.

1. **Independent drafts.** Start two subagents, each tasked with extracting the entire supplied document. Give both the source path, this skill, the schema paths, and separate temporary output locations. Each must read the full skill, all schema files, and the document, independently build its own experiment/process inventory, and perform the coverage and semantic reviews. Neither may see the other inventory, draft, or previous extraction results before submitting its own draft.
2. **Source support.** Each subagent returns its inventory with coverage outcomes, candidate rows, and exceptions, with supporting passages and source locations for populated values and relationships, including page, table, figure, or panel identifiers where available. Keep review material separately from the candidate JSONL; do not add fields to the schema.
3. **Compare.** After both drafts are complete, the main agent aligns records by source-supported entity identity, experimental group, and measurement conditions, not row order or generated UUIDs. Compare inventories as well as values, attribution, parameter coverage, missing records, and cases where only one draft identifies an experiment, group, or value.
4. **Resolve from the source.** Re-read the relevant text, tables, or images to resolve differences. Another agent's answer, agreement, or majority vote is not evidence. Also review source sections, Methods, captions, and tables for omissions shared by both drafts; agreement between inventories does not establish complete coverage. Spot-check agreeing results against the source, especially numerical values and entity relationships. Apply the existing missing-information and conflicting-evidence rules when the source remains ambiguous or contradictory; a disagreement between drafts alone is not a conflict in the source.
5. **Final output.** Only the main agent writes final `data.jsonl`, optional `error_log.jsonl`, and `reasoning.md`. Reconcile identifiers and references across accepted records, and log exceptions according to the final decisions rather than copying both draft logs. Follow the existing output format and completion checks.

If subagents are unavailable or two independent drafts cannot be completed, finish using the single-agent workflow and disclose the limitation in the final response. State whether the cross-check was completed; do not claim it occurred when it did not. Record this execution status in `reasoning.md`, keeping it out of the extracted rows and source-exception sidecar.

## Read the source

Supported input formats match `scripts/run_extraction_agent.py`: `.pdf`, `.xml`, `.nxml`, `.md`, and `.markdown`. Report other formats as unsupported.

- **XML/NXML:** read the article content directly. Exclude reference lists and acknowledgments from extraction; do not discard the entire `<back>` section because it may contain relevant appendices or supplement links.
- **Recover missing source material for every input format**, including BigQuery Markdown/text exports. If a relevant figure, table, supplement, or sequence listing is referenced but absent, look locally first, then attempt online retrieval with available network tools (or permitted shell HTTP downloads) before treating it as unavailable. This is part of source reading, not an optional follow-up for the user.
  - Resolve the article using its DOI/PMCID, or the patent using its publication number including kind code. For PMC articles, use the cloud-resource procedure below before relying on article landing pages; otherwise prefer the publisher page and linked supplements, or the exact patent publication's Google Patents/patent-office page and linked PDF, drawings, and sequence listing. Verify identity and version before using retrieved content; do not substitute a related paper, patent-family member, or granted version for the supplied publication.
  - Follow actual source-page, document, or official metadata links. Requests constructed from documented API rules and source identifiers are allowed; do not invent asset paths. For XML/NXML, inspect figure labels, captions, `<graphic xlink:href>`, tables, and supplementary-material links; relative filenames need resolution against the source. For text exports without links, resolve the matching source through official metadata or its source page first. Retrieve only material relevant to extraction, reusing downloads within the run.
  - Retrieved material verified as part of the same source is eligible evidence under this skill. Search snippets, captions alone, and unrelated external knowledge cannot substitute for the missing content.
  - Actually inspect downloaded images or rendered PDF pages with an image-viewing tool, together with captions and panel labels. Read tables with row/column headers, units, and footnotes; read sequence listings with their SEQ ID identifiers. A successful download alone does not establish readable evidence. Extract explicitly labeled numbers only; do not estimate values from bar heights or curves. SD/SEM must be supported by text or legends.
  - Keep downloads in temporary locations, or within the runner's private staging directory when required by its output override. Record source-page and asset URLs, retrieval date, inspected figure/table/page/SEQ ID locations, and affected fields in `reasoning.md`; retain the original source identity in evidence rows and use schema-supported citation fields for locations.
  - Stop once the needed material is obtained or applicable resource routes below have been checked and a relevant alternative is exhausted. A landing-page 403 or browser challenge does not establish that its images or supplements are unavailable. Use bounded request timeouts, respect the run budget and access controls, and do not repeatedly retry a blocked endpoint. If network/image tools are unavailable, access fails, identity is uncertain, or content remains unreadable, retain readable evidence and log only the unresolved affected fields/records using existing exception categories. State attempted URLs and failure reasons in `reasoning.md`; do not report successfully recovered content as still missing.
- **PDFs:** when text extraction loses table alignment, image content, or sequence characters, render and inspect the affected pages. A caption or URL alone does not count as viewing a figure.
- Read measurements with their row/column headers, units, footnotes, groups, and panels. Extract explicitly labeled numbers, not estimates from bar heights or curves. Identify SD/SEM from the source, not the appearance of error bars.
- Verify suspected OCR errors against the page image. If content remains unreadable or image tools are unavailable, preserve readable information and log only the affected fields or records.

### Resolve PMC images and supplements from XML/NXML

Use this procedure for missing resources in a PMC source, including text exports with a verified PMCID. Resource discovery and retrieval are the extracting agent's responsibility; a local XML without companion images is a starting point, not a terminal failure.

1. Collect the PMCID, `pmcid-ver` when present, DOI, and relevant figure labels/IDs with their `<graphic xlink:href>` filenames, supplementary-material links, and PDF references. Match relative filenames to retrieved resources; do not treat a bare filename as a complete URL.
2. Prefer the current [PMC Cloud Service](https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/) and its [dataset README](https://pmc-oa-opendata.s3.amazonaws.com/README.txt). For a source version such as `PMC12182840.1`, fetch `https://pmc-oa-opendata.s3.amazonaws.com/PMC12182840.1/PMC12182840.1.json`. Verify PMCID, DOI when available, and version against the input; use `media_urls` for images/supplements and `pdf_url` for the article PDF. This documented metadata request is not a guessed asset URL. Legacy FTP/OA-service package workflows are no longer the default following the August 2026 migration.
3. If the version is absent or its metadata is unavailable, list actual keys using `https://pmc-oa-opendata.s3.amazonaws.com/?list-type=2&prefix=PMC12182840.&delimiter=/`, then inspect candidate metadata and source content. Do not assume version 1 exists or choose the largest version number automatically. List a verified version's files with `?list-type=2&prefix=PMC12182840.1/` when needed; opening the prefix as an object is not a directory listing. Follow continuation tokens if a listing is truncated. Consult the official documentation if the service layout changes.
4. Match XML references to the filenames in the returned media URLs or object listing. Download the returned resources; an `s3://pmc-oa-opendata/<key>` URL can be accessed anonymously as `https://pmc-oa-opendata.s3.amazonaws.com/<key>`. Preserve the key and verify the provided `md5` checksum when present. Check file signatures/types and that images or PDFs open successfully; HTTP 200 containing a browser-challenge HTML page is not success. Actually inspect relevant images or rendered PDF pages under the source-reading rules above.
5. For unresolved resources, try an applicable independent route: the [Europe PMC supplementary-files API](https://europepmc.org/RestfulWebService) at `https://www.ebi.ac.uk/europepmc/webservices/rest/{PMCID}/supplementaryFiles`, or actual publisher resource links for the verified article. Inspect any returned archive for the required filenames; do not assume it contains every main figure. If a separate image remains unavailable but the matching full-text PDF is accessible, inspect the figure there and record that fallback. A main-text PDF does not replace a missing supplement.
6. Track each relevant resource's XML reference/figure label, resolved URL, temporary local path, and whether it was downloaded and inspected. Summarize coverage and unresolved failures in `reasoning.md` within the existing three-file output contract. Distinguish network/DNS or access failures, resources absent from a retrieved listing, identity mismatches, and unreadable files. Check applicable machine-readable resource routes before declaring content unavailable; if execution permissions or tools prevent a check, report that limitation rather than claiming the route or resource was exhausted. Stop retrying blocked endpoints, retain supported evidence, and log only affected unresolved fields using existing exception categories.

## Coverage and semantic review

Apply these steps in both single-agent and enabled independent-extraction modes.

### Inventory before extraction

Build a temporary inventory from Methods, Results, captions, and tables, with one entry per source-described experiment or independent process, not per parameter. Include source locations, the measured or processed subject, actual groups and conditions, and readouts where applicable. Add source-supported entities from claims or embodiments under the extraction-scope rules below; an experiment inventory must not exclude otherwise eligible entity data.

Keep the inventory open to additions during extraction and review. Record only combinations of conditions actually reported; do not generate a Cartesian product of doses, time points, or groups. Distinguish inaccessible source content from information not reported, using the source-recovery rules above.

### Coverage review: what was missed?

After drafting, return to source sections, Methods, captions, and tables rather than checking only populated fields or the initial inventory. For source-reported information with an active schema destination, check:

- **Operations:** subject, steps, reagent names and product identifiers, amounts or concentrations, times, temperatures, equipment, and post-processing.
- **Experiments:** experimental and control groups, doses or E:T ratios, time points, tissues, sample sizes, replicates, and readouts.

Do not replace explicit parameters or enumerated groups with a broad summary. An experiment without exact numerical results may still support qualitative or method information where an active field permits it; do not force that information into a numerical or unrelated field. Facts already fully stored in the correct location need not be duplicated for coverage. Do not invent unreported checklist items.

Give each inventory entry a final disposition: covered, partially covered, or not stored. For gaps, distinguish unavailable input, unresolved source evidence, no active schema destination, and exclusion under the collection scope. Resolve omissions that the source and schema permit before finishing; a disposition alone does not justify leaving an extractable fact out. Summarize these outcomes in the existing `reasoning.md`, not a new output file.

### Semantic review: was the meaning changed?

Check the source against the draft for subject and foreign-key agreement, molecular format, process stage, measurement meaning, units, comparison bounds, negation scope, comparison groups, and unresolved conflicts. In particular, a subject named in descriptive context must agree with the structured links. Apply the detailed attribution, value, and conflict rules below; remove unsupported assertions and retain unresolved source conflicts without selecting a preferred answer.

## Decide what to extract

**Entities:** A is the Binder, B is the CAR backbone, and C is the manufacturing process. Follow their YAML definitions to separate entity properties from measured evidence. Extract all source-supported records, not just one record per document.

Create an entity only when the document treats it as part of its own claims, embodiments, experiments, results, or actually tested controls, with meaningful data or relationships beyond a name. Ignore background mentions, prior-art surveys, citations, and generic example lists without creating placeholder rows or exceptions.

Reuse an entity across its experiments when identity is clear. Do not merge entities merely because names are similar. Preserve source names and identifiers; broader entity deduplication happens downstream.

**Binder identity versus measurement format:** A Binder ID identifies the binding domain under Schema_A. When the source establishes the same binding domain, an Fc fusion, purification tag, expression vector, or CAR display used for an experiment does not create a new Binder. Record the tested molecular format in evidence `applicable_scenario` and retain assay conditions and fitting models in their designated fields. Do not put fusion constructs or vector names into Binder aliases. Changes to the binding domain's own sequence or structure require source-based identity assessment; a shared clone name alone is insufficient to merge records. For example, FMC63 scFv and its experimental FvFc fusion share one Binder ID, while the FvFc BLI evidence retains the Fc-fusion format and bivalent-analyte model; do not describe that result as a measurement of free scFv. Merge duplicate entities without merging distinct experiments or transferring format-specific results to another format.

Before assigning a fact to a field or foreign key, establish its subject, molecular format, and process stage. Viral production, T-cell manufacturing, functional assays, and animal administration do not inherit one another's parameters merely because they belong to the same study. A shared clone identifier does not make measurements in monovalent and bivalent formats interchangeable. Distinguish measurement formats in evidence; this does not by itself require separate Binder entities. Vector or reagent catalog/lot identifiers are not Binder aliases.

**Manufacturing identity versus product:** C identifies a reusable manufacturing protocol, not one product, donor, batch, or measured outcome. Where the source establishes a shared protocol, different A/B identities, product names, or CAR-coding sequences in the same delivery system do not by themselves create new C entities. Compare actual selection steps, delivery system and amounts, activation timing, culture conditions/duration, and downstream processing; distinguish protocols with different steps or key conditions. Similar names or equally missing fields do not establish equivalence. Keep shared reagent descriptions accurate (for example, pT4 encoding the corresponding CAR, 20 µg), retain product-specific construct identity through the ABC links and source-supported evidence context, and if `corresponding_car_product` is active, follow its current schema type and use it only descriptively, not as an entity-splitting criterion. Product-specific outcomes retain their corresponding A/B/C references and experimental groups even when C is shared; never merge distinct evidence rows merely because their manufacturing ID becomes identical. This identity rule does not decide whether negative controls belong in the collection. Do not infer the presence or absence of a CAR, or any manufacturing steps, solely from a negative-control label; use the actual source-described construct and treatment. Do not create a C entity solely to provide a foreign-key target for control evidence, and do not infer exclusion solely from control status; apply the existing entity-eligibility and provenance rules.

Different Binders do not automatically require different B entities: B represents the backbone. Where the source establishes a shared backbone, preserve distinct product combinations and experiment attribution through the appropriate relationships. Missing backbone information in multiple products is not evidence that their backbones are identical.

Distinguish generic options, concrete proposed embodiments, and experimentally used constructs. Do not populate an experimental construct's actual modules from a generic candidate list without an explicit source link. Apply the collection-scope rule above to concrete claims and embodiments; do not exclude them solely because they are untested.

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
- Keep descriptive values concise, but do not delete source-supported facts to shorten a field. Use defined subfields for structured content and retain only field-relevant facts in strings, preserving source terminology and necessary qualifications. Do not add your own explanations or bracketed reasoning. Source parentheses, measurement `raw`, and necessary experimental details may be retained.
- Distinguish not reported, not detected, no significant difference, no antigen-dependent increase, and zero; do not substitute one for another. Low bars or absent numerical labels do not support a claim of non-detection.
- Use active condition fields for the corresponding assay. Do not emit commented-out `experimental_conditions` or invent a replacement field. Preserve context in `raw` where its field definition permits; information without a current schema destination is omitted without an exception against another field.
- `evidence_level` is assigned downstream: do not emit it, invent a score, or drop evidence because it is absent. For dates, distinguish source upload/download metadata from publication dates and the extraction date; unreported dates remain `null`.

## Measurements and sequences

For `measurement`, follow the structure and `kind` definitions at the top of `Evidence.yaml`. Even a single number is an object with `kind`, `value`, `lower`, `upper`, `error`, `unit`, and `raw`; unused members are `null`.

Preserve source values, units, statistical meaning, and denominators. Do not collapse ranges, turn mean ± SD into a range, guess SD versus SEM, or assign a pooled range to one entity. Missing units stay `null`; `preferred_unit` does not establish the source unit. Follow any field-specific ratio representation. Otherwise leave conversion to the normalization command below; unsupported conversions are not extraction exceptions.

Preserve the inclusiveness of bounds: `minimum of` and `at least` mean ≥ (`greater_than_or_equal`), whereas `more than` means > (`greater_than`). Keep the source comparison object and scope; do not strengthen a bounded or qualified claim.

Copy sequences exactly, removing only layout whitespace and joining blocks in unambiguous reading order. Verify unreadable or OCR-corrupted characters against the source image; never repair them from expected biology. If unresolved, leave the affected sequence field `null` and log the exception.

Do not reconstruct missing regions or infer VH/VL/linker/module boundaries without explicit or unambiguous source support. Before comparing sequences, distinguish full expression constructs, CAR proteins, fragments, and individual modules. Differences in scope alone do not establish a conflict. Use the schema's coordinate and chain-scope definitions.

## Conflicts and provenance

For conflicting measurements with clear identity and context, retain the attributable values in separate evidence rows with exact source locations and log the conflict. Do not select a preferred value or alter the source. When identity or attribution is uncertain, retain unambiguous data and leave affected nullable fields `null`; omit a record only if its identity cannot be established.

Use actual source identifiers such as DOI, PMCID, patent accession, or internal document ID. Never invent them. In `citation`, include the source reference and available page, section, table, figure, or panel location for the evidence. Do not invent page numbers. Interpret `contrary_evidence` from source-supported context: it identifies evidence contrary to the main conclusion, not merely a negative result, a weaker result, a control group, or disagreement between extraction drafts.

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
* a compact coverage table with one row per inventory entry: experiment/process or eligible entity and source location; covered/partially covered/not stored; output table, row number, and field, or the reason for a gap. Use one-based physical line numbers in final `data.jsonl`, refreshing references after edits. Summarize parameter coverage within the entry rather than listing every parameter separately;
* whether the coverage review, semantic review, independent cross-check (when enabled), and final validation completed, plus any limitations.

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

- Check whether manufacturing records were split solely by product, A/B identity, donor, batch, or outcome. Reuse C only for source-established shared protocols; after merging, verify ABC/evidence links still distinguish products and controls and that distinct experiments remain separate.

- Check for Binder duplicates created solely by Fc fusions, tags, vectors, or display formats. Merge only when the source establishes the same binding domain, update references, and retain each experiment and its measurement-format limitations.

- Verify the inventory was checked against the source, including Methods, Results, captions, and tables, and that each entry has a final disposition. Check for missing parameters, groups, controls, time points, and tissues wherever the active schema can store them.
- Complete the semantic review of attribution, molecular formats, process stages, comparison bounds, and negation scope. Cross-check values, entity links, groups, and source locations; resolve discrepancies from the document rather than another model's answer.
- Parse each output line and check field names, shapes, types, enums, missing values, and required provenance against active YAML. Check identifiers against the active execution contract (UUIDs by default or document-local labels under the runner override), foreign-key targets, and row order. YAML `check`/`pattern` rules are not automatically enforced by every project parser; do not claim validation merely because JSON parses.
- Verify normalization succeeded (or was explicitly delegated to the runner), and only current-run exceptions remain. Verify the final document folder contains only `data.jsonl`, `reasoning.md`, and optional `error_log.jsonl`; scratch files in runner staging must remain separate from these publishable artifacts. Check that the non-empty reasoning summary reflects the final records and actual cross-check/validation status.
- Count written rows by table and exceptions from the files. Report counts, unresolved failures, and whether extraction was single-agent or independently cross-checked.
