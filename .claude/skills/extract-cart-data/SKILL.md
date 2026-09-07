---
name: extract-cart-data
description: Use when extracting structured data from a scientific paper, patent, public database record, or internal research document into this repo's CAR-T database — reads the document, maps it onto docs/Schema/*.yaml, and writes data/normalised/{stem}.jsonl plus an .errors.jsonl sidecar.
---

# CAR-T Document Extraction

## Role

You are a biomedical data extraction agent for a CAR-T research database.

Your task is to extract structured information from scientific literature, patents, public database records, and internal research documents and map the extracted information to this repository's database schema.

The database focuses on CAR-T research and contains four major types of entities:

* **A: Binder**
* **B: CAR backbone**
* **C: Manufacturing process**
* **ABC combination: a specific Binder + CAR backbone + Manufacturing process combination**

Experimental evidence associated with these entities is stored separately from the entities themselves.

---

## Workflow

1. **Read the schema.** Read every file in `docs/Schema/*.yaml` before extracting. These are authoritative: `Schema_A.yaml` (binder), `Schema_B.yaml` (car), `Schema_C.yaml` (manufacturing), `Schema_DB1.yaml` (abc_combination_db1), `Evidence.yaml` (evidence). Do not work from memory of a previous run — the schema changes.
2. **Read the document.**
   * `.md` / `.markdown` / `.xml` / `.nxml` / `.pdf` / `.txt` — read the file directly. For JATS XML, ignore the `<ref-list>`, `<back>` and `<ack>` sections; they hold no extractable content.
   * For XML / NXML figures:
     * Inspect each `<fig>` label, caption, and `<graphic xlink:href>` to identify images relevant to the fields being extracted.
     * Look for the image locally first. If absent, use available network tools and the article DOI, PMCID, or source page to resolve and retrieve it. `xlink:href` may be a relative path or filename; do not guess image URLs. Retrieve images on demand; temporary local files are sufficient.
     * Use an available image-viewing tool to actually inspect the image, together with the body text, caption, legend, and panel labels. Reading a URL or caption alone does not count as viewing the image.
     * Associate image-derived values with the specific experimental group and retain the figure and panel in the source location, such as `Figure 2B`. Extract explicitly labeled numbers only; do not estimate values from bar heights or curves. SD / SEM must be supported by the text, caption, or legend, not inferred from the appearance of error bars.
     * If image viewing is unavailable, or an image cannot be retrieved or read, record the reason using the existing exception rules and continue extracting readable content.
   * For PDF documents, if extracted text loses table alignment, figure content, or sequence characters, render and inspect the relevant pages using an available image-viewing tool before declaring the content unreadable. Read table values together with their row headers, column headers, units, and footnotes. Verify suspected OCR errors against the page image; do not repair them from biological expectations. If the page remains unreadable or cannot be viewed, leave only the affected fields null and log the exception.
   * Any other extension is unsupported — stop and say so.
3. **Extract and cross-check** every source-supported record using the independent extraction workflow below and the rules in this skill.
4. **Write** `data/normalised/<source-stem>.jsonl` in the row format below, and append any exceptions to `data/normalised/<source-stem>.errors.jsonl`. If there are no exceptions, do not create the error file.

### Independent extraction and cross-check

The main agent coordinates this workflow. Subagents perform only their assigned extraction; they must not spawn further subagents or write the final output files.

Respect user-specified subagent models. When model selection is supported and the user has not specified a model, prefer an available lower-cost model capable of full-document extraction, including the required context length, image understanding, and tool use. Apply the choice through actual tool parameters or agent configuration, not merely the task description. If model selection is unavailable, use the inherited model without claiming a different model was used.

1. **Independent drafts.** Start two subagents, each tasked with extracting the entire supplied document. Give both the source path, this skill, the schema paths, and separate temporary output locations. Each must read the full skill, all schema files, and the document. Neither may see the other draft or previous extraction results before submitting its own draft.
2. **Source support.** Each subagent returns candidate rows and exceptions, with supporting passages and source locations for populated values and relationships, including page, table, figure, or panel identifiers where available. Keep review material separately from the candidate JSONL; do not add fields to the schema.
3. **Compare.** After both drafts are complete, the main agent aligns records by source-supported entity identity, experimental group, and measurement conditions, not row order or generated UUIDs. Compare values, attribution, missing records, and cases where only one draft supplies a value.
4. **Resolve from the source.** Re-read the relevant text, tables, or images to resolve differences. Another agent's answer, agreement, or majority vote is not evidence. Also spot-check agreeing results against the source, especially numerical values and entity relationships. Apply the existing missing-information and conflicting-evidence rules when the source remains ambiguous or contradictory; a disagreement between drafts alone is not a conflict in the source.
5. **Final output.** Only the main agent writes the final JSONL and exception sidecar. Reconcile identifiers and references across accepted records, and log exceptions according to the final decisions rather than copying both draft logs. Follow the existing output format and completion checks.

If subagents are unavailable or two independent drafts cannot be completed, finish using the single-agent workflow and disclose the limitation in the final response. State whether the cross-check was completed; do not claim it occurred when it did not. Keep this execution status out of the extracted rows and source-exception sidecar.

---

## Objectives

### Primary objective

Extract every source-supported value from all supplied document content, including:

* body text
* tables
* figure and table captions
* figures, diagrams, labels, and other image content when they are supplied in a readable form
* supplementary content when it is included in the input

Map each value to the corresponding field in the schema. For every schema field applicable to an extracted record, return either:

* the supported value in the schema's required type; or
* `null` when no supported value can be found.

The objective is faithful extraction, not record completion. A missing value is preferable to an inferred, guessed, or type-invalid value.

### Field-level objectives

Before filling each field, briefly assess it internally in this order:

1. Determine from the schema whether the field is an enum-like string with `allowed_values`, a continuous numerical value, or another declared type.
2. Locate direct supporting evidence in the supplied source content.
3. Check that the candidate value matches the field meaning and declared type.
4. Apply the field-specific rules below.
5. If any check fails, use `null`; do not force a value.

For an enum-like string field:

* Return only a value present in `allowed_values`.
* Map source wording to an allowed value only when the equivalence is direct and unambiguous from the supplied source and schema.
* Do not select the closest allowed value when the mapping is uncertain.

For a continuous numerical field:

* Confirm that the source reports a number, range, bound, or other explicit quantitative value rather than only a qualitative description.
* Preserve the reported unit, range, bound, and measurement context whenever the schema provides a place for them.
* Do not turn qualitative wording into a number or collapse a range to a single value.

Perform this assessment internally. Do not write the assessment or its explanation into the output file.

---

## Database Semantics

You must distinguish between:

### Entity data

Information describing what an entity **is**.

Examples:

* Binder amino-acid sequence
* Binder target antigen
* CAR module composition
* CAR module sequence
* T-cell source used by a manufacturing process
* activation method
* vector type
* MOI

### Evidence data

Information describing an **observed or measured result** associated with an entity.

Examples:

* Kd
* Kon / Koff
* Tm
* CAR-T expansion
* exhaustion phenotype
* transduction efficiency
* VCN
* killing activity
* cytokine release

### Experiment data

Information describing **where the evidence came from and under what conditions it was produced**.

Examples:

* source
* experimental conditions
* citation
* evidence level
* applicable scenario
* whether the evidence contradicts another reported conclusion

Do not merge these concepts.

---

## Schema

`docs/Schema/*.yaml` is authoritative. Follow it exactly.

For every field:

* Use the field definition and description in the schema to determine its meaning.
* Respect the declared data type.
* Respect `allowed_values` when defined.
* Do not create fields that are not present in the schema.
* Do not rename schema fields.
* Do not invent values merely to make a record complete.

Match the reported quantity to the field's meaning before checking its numeric format or readability. Similar names, shared units, or correlated biological effects do not make two measurements equivalent.

In particular:

* EC50 is not Kd.
* Viral titer is not transduction efficiency.
* CAR-positive or CD8-positive percentages are not CD3-positive percentages.
* CD107a and cytokine measurements are not target-cell killing percentages.
* Clinical Cmax and AUC are not manufacturing VCN in copies/cell.

If information in the document does not map to any schema field, ignore it without logging an exception against a different field.

Apply the same semantic check to descriptive fields: an assessment on day 10 alone does not establish total culture duration. An explicitly identified antigen domain may support `epitope.identified_area` without residue-level mapping, but competition groups alone do not identify a concrete epitope.

Some features have examples, all of them are synthetic. They only exist for hints of the output
structure but not any real information. You do not have to 100 % follow the examples. 

---

## Hard Boundaries and Extraction Rules

The rules in this section are hard boundaries. Never cross them merely to produce a more complete-looking record.

In particular, never:

* invent or guess a value;
* use external knowledge to fill a gap in the supplied source;
* force ambiguous wording into an enum or numerical field;
* treat unreadable text, tables, figures, image labels, or OCR fragments as reliable evidence;
* combine values from different entities, experiments, groups, panels, time points, or sources unless the source explicitly establishes the relationship;
* reconstruct missing sequence regions or unreported experimental values;
* alter a reported result to resolve a conflict; or
* create, rename, or repurpose schema fields.
* add explainatory brackets.
* quote or summarise a long sentence as the string value.
* use previous extraction results to fill in information. Independent drafts must be produced without consulting other results; the main agent may compare the current drafts only through the cross-check workflow above and must ground final decisions in the source.

### 1. Extract only supported information

Only extract information that is explicitly stated in the source or can be directly and unambiguously derived from it.

Do not use external biological knowledge to fill missing fields.

Do not guess.

Do not infer an exact value from vague language.

For example:

> "The CAR showed strong antitumor activity."

may support a qualitative experimental outcome if an appropriate schema field exists.

It does **not** support inventing a numerical killing rate.

Do not create entity records for names that appear only in background sections, prior-art surveys, general technical discussion, citations, or lists of examples. A name, alias, target, or other isolated descriptive detail does not by itself make the item an extractable entity. Create a record only when the supplied document treats the item as a subject or component of its own claims, embodiments, experiments, or results, or as an actually tested control, and supports meaningful entity data, evidence, or a relationship beyond the mere mention. Otherwise ignore it; do not emit a mostly `null` placeholder row or an exception.

---

### 2. Missing information

If a schema field is not reported in the source, is unreadable, is ambiguous, cannot be mapped without guessing, or cannot be represented in the declared type, write `null`.

Never use the literal string `"missing"`. Do not omit an applicable schema field; write its key with a `null` value instead.

Never replace missing information with:

* guessed values
* typical values
* values from general biological knowledge
* values from another experiment unless the source explicitly establishes that they are shared

---

### 3. Preserve experimental context

A measurement is meaningful only together with the experiment that produced it.

Do not combine results from different experiments into one evidence record merely because they concern the same Binder, CAR, or manufacturing process.

If the document reports multiple experiments under materially different conditions, write separate evidence rows.

---

### 4. Separate entities from observations

The same entity may appear in multiple experiments.

Do not create a new Binder, CAR backbone, or manufacturing process merely because it was tested multiple times.

Conversely, do not merge two entities merely because they have similar names.

Entity resolution will be handled separately unless identity is explicit in the source.

---

### 5. Preserve source terminology

Preserve reported names, identifiers, sequences, constructs, products, experimental groups, and other source-specific terminology whenever possible.

Do not silently replace the author's terminology with a preferred biological synonym.

Normalization and entity deduplication are separate downstream steps.

---

### 6. Numerical values

For fields declared `measurement`, follow the structure and `kind` definitions at the top of `docs/Schema/Evidence.yaml`:

* Always return an object with `kind`, `value`, `lower`, `upper`, `error`, `unit`, and `raw`, even for a single number. Write unused numerical members as `null`; write an unreported nullable measurement as `null`.
* Use only the full, readable `kind` names documented there. Preserve the original quantitative text, unit, and statistical meaning in `raw`.
* Distinguish mean ± standard deviation from mean ± standard error using the source text or captions. If the meaning of ± is not stated, use `plus_minus_unspecified`; never guess.
* Keep ranges and comparison bounds as reported. Do not turn mean ± SD into a range or assign a multi-entity summary range to an individual entity.
* Extract numerical members and `unit` as reported; do not convert them yourself. `preferred_unit` is a normalization preference, not an allowed-unit restriction. If the source omits the unit, retain the number with `unit: null`; never infer the unit from the preference. An unconvertible unit is not a `schema_mismatch` and does not make the measurement missing.
* Keep the measurement's unit inside the measurement object, not in a sibling field. Preserve denominators and methods in experimental conditions; shared units do not make different indicators comparable.
* `number` and `integer` fields keep their scalar types, including sequence lengths, residue positions, and fixed scores. A valid range or ± expression in a `measurement` field is not a type exception.

Extract the numerical value and unit when reported.

Do not perform speculative unit conversion.

For measurements, run the normalization command below after writing the JSONL. It applies supported fixed conversions to all numerical members, scales errors without offsets, and leaves `raw` unchanged. Unsupported conversions retain the source values and units.

Ranges must remain ranges unless the schema explicitly requires another representation.

Do not convert:

> Kd = 2–5 nM

into:

> Kd = 3.5 nM

---

### 7. Sequences

Copy biological sequences exactly as reported. Whitespace used only to group or wrap sequence characters is formatting, not sequence content: remove spaces, tabs, and line breaks, and concatenate the blocks when their reading order is unambiguous. Do not set a sequence to `null` or log an exception solely because it is split into fixed-width blocks such as groups of 10 residues.

After removing layout whitespace, preserve every source-supported residue character. If any character remains unreadable, appears OCR-corrupted, or the block order is ambiguous, do not silently correct or infer it; set the field to `null` and log the specific exception.

Do not reconstruct missing sequence regions.

Do not infer VH, VL, linker, CAR modules, or other sequence components unless their boundaries are explicitly reported or unambiguously defined by the source.

Before comparing a sequence listing with a construct description, determine what each represents: the full expression construct, the CAR protein, a CAR fragment, or an individual module. Treat a component as missing or contradictory only when both passages explicitly describe the same sequence scope. Do not force components outside the schema's module categories into another category.

All other sequence normalization will be handled downstream.

---

### 8. Conflicting evidence

Distinguish conflicting values from uncertain identity or attribution.

When the entity and measurement context are clear, preserve conflicting reported values in separate evidence rows with their exact source locations. Do not choose a preferred value, silently correct the source, or present repeated descriptions of the same experiment as independent experiments.

When identity or attribution is uncertain, do not assign the disputed values to an entity merely because a label is repeated. Preserve the unambiguous data, leave the affected fields null, and omit a candidate record only when its identity cannot be established.

Log the conflict and make the action match what was actually done.

If the source explicitly presents a result as contrary evidence, record this using the corresponding schema field.

---

### 9. ABC combinations

Create an ABC combination only when the source provides sufficient information to associate:

* a Binder,
* a CAR backbone,
* and a manufacturing process

with the same experimental system or product.

Do not construct an ABC combination by combining A, B, and C information from unrelated parts of the document.

If only A+B, A+C, or B+C are identifiable, extract the identifiable entities and evidence, but do not fabricate the missing component.

---

### 10. Multiple records

A single document may describe:

* multiple Binders
* multiple CAR backbones
* multiple manufacturing processes
* multiple ABC combinations
* multiple experiments

Extract all distinct records supported by the source.

Do not assume one document corresponds to one database record.

---

## Provenance

Every extracted evidence row must remain traceable to its source.

Use the source metadata available in the document, including identifiers such as:

* DOI
* PMID / PMCID
* patent number
* database accession
* internal document or batch identifier

Do not invent source identifiers.

---

## Output

Write `data/normalised/<source-stem>.jsonl`: one JSON object per line, UTF-8, **not** ASCII-escaped (Chinese must stay readable). Every line is `{"table": ..., "data": {...}}`.

You assign the identifiers. Every `*_id` and `record_id` is a UUID4 string you get from the uuid package, the package is under the fosun conda environment.

After writing the JSONL, normalize its measurement units using the repository's Python environment (replace the path with the actual output file, including any output-directory override):

```bash
PYTHONPATH=src /home/zzz010122/anaconda3/envs/fosun/bin/python -m cart_db.measurements data/normalised/<source-stem>.jsonl
```

This updates the file in place. Do not rewrite the normalized values afterward. Missing or unsupported units are retained; they do not require an exception.

### Row order

Rows must appear in this order, because a row may only reference an identifier that already appeared above it:

1. entity rows — `binder`, `car`, `manufacturing`
2. combination rows — `abc_combination_db1`
3. evidence rows — `evidence`

### Entity rows

One row per distinct entity. `data` holds the primary key you generated plus every non-key field of that table in the YAML:

```json
{"table": "binder", "data": {"binder_id": "<uuid4>", "name": "ARB-202", "scfv_sequence": null, "...": "..."}}
```

`car` uses `car_id`, `manufacturing` uses `manufacturing_id`.

### Combination rows

Only for a Binder + CAR + manufacturing process the source ties to the same experimental system or product. The three foreign keys are the UUIDs of entity rows you already wrote:

```json
{"table": "abc_combination_db1", "data": {"combination_id": "<uuid4>", "binder_id": "<binder uuid>", "car_id": "<car uuid>", "manufacturing_id": "<manufacturing uuid>", "similarity": null, "completed_experiment_phase": "in_vitro"}}
```

### Evidence rows

`Evidence.yaml` has two kinds of field. Fields without a dot (`source_type`, `source_id`, `citation`, `evidence_level`, `experimental_conditions`, `applicable_scenario`, `contrary_evidence`, `time_of_upload`, `time_of_download`) are shared by every evidence row. Fields with a dot belong to one owner: `binder.kd` is a Binder measurement, `car.memory_phenotype` and `manufacturing.memory_phenotype` are different columns despite the shared name — write the dotted name exactly as the YAML spells it.

Every evidence row carries all three foreign-key columns `binder.binder_id`, `car.car_id` and `manufacturing.manufacturing_id`. For a measurement on a single entity, only that entity's column is filled and the other two are `null`; write only that owner's dotted fields:

```json
{"table": "evidence", "data": {"record_id": "<uuid4>", "source_type": "literature", "source_id": "PMC1234567", "evidence_level": "in_vitro", "contrary_evidence": false, "binder.kd": {"kind": "single_value", "value": 2.4, "lower": null, "upper": null, "error": null, "unit": "nM", "raw": "2.4 nM"}, "binder.binder_id": "<binder uuid>", "car.car_id": null, "manufacturing.manufacturing_id": null}}
```

For a result measured on the combination as a whole, all three foreign keys are filled and no dotted measurement fields are written — only the shared fields:

```json
{"table": "evidence", "data": {"record_id": "<uuid4>", "source_type": "literature", "source_id": "PMC1234567", "evidence_level": "in_vivo", "contrary_evidence": false, "binder.binder_id": "<binder uuid>", "car.car_id": "<car uuid>", "manufacturing.manufacturing_id": "<manufacturing uuid>"}}
```

`source_id` and `evidence_level` are required. An evidence row missing either one is dropped — log it and move on.

### Field types

* `measurement` is a single object as defined at the top of `Evidence.yaml`, stored in JSONB.

* A field declared `json` with an `item_schema` is a list of objects with those fields (e.g. a CAR's `modules`).
* A field declared `json` with an `item_type` is a list of scalars of that type.
* A field declared `json` with neither is written as a JSON object or array of your own shaping — these land in `jsonb` columns.
* `date` is an ISO 8601 string.
* `uuid` is a UUID4 string.

---

## Exception Handling

Handle exceptions at the smallest safe scope:

1. **Field-level:** If one field is unreadable, ambiguous, outside `allowed_values`, type-invalid, or unsupported, write `null` for that field only and continue extracting the record.
2. **Record-level:** If a record cannot satisfy a required identity, provenance, or relationship constraint without fabrication, omit only that record and continue with the others.
3. **Document-level:** If the document is empty, unreadable, or cannot be processed reliably as a whole, write an empty `.jsonl` file. Do not fabricate a placeholder record.
4. **Conflicting evidence:** Follow section 8 to distinguish conflicting values from uncertain identity or attribution; preserve attributable results and log the conflict.

### Exception log

Append every exception to `data/normalised/<source-stem>.errors.jsonl`, one JSON object per line:

Log an exception only when a concrete schema field, candidate record, or the document as a whole cannot be handled normally because its supplied evidence is unreadable, ambiguous, invalid, conflicting, or insufficient for a required constraint. Do not log ordinary unreported optional fields, source-type reasoning, extraction rationale, background material that is intentionally excluded, or information that has no corresponding schema field. Ignore those cases without creating a `notes` field or a `schema_mismatch` entry. A conflict that affects an extracted field or relationship is still an exception and must be logged separately.

```json
{
  "source": "article.pdf",
  "stage": "validation",
  "record_index": 3,
  "field": "manufacturing.moi",
  "reason": "invalid_numeric_value",
  "raw_value": "high MOI",
  "action": "set_missing"
}
```

Use `null` for properties that do not apply. `reason` must use the most specific applicable category:

* `unreadable_source`
* `ambiguous_evidence`
* `invalid_enum`
* `invalid_numeric_value`
* `schema_mismatch`
* `missing_required_provenance`
* `unsupported_relationship`
* `output_validation_error`

`action` must state the actual handling decision: `set_missing`, `omit_record`, `return_empty_result`, or `preserve_conflicting_values` (when conflicting values are retained in separate evidence rows).

The exception log is a sidecar file. Never add exception-log fields to the extracted rows.

---

## Before you finish

Verify that:

1. every extracted value is supported by the source;
2. every field exists in `docs/Schema/*.yaml`;
3. entity information and experimental evidence are not mixed;
4. different experiments have not been incorrectly merged;
5. missing values are `null`, not guesses;
6. enum-like fields contain only allowed values;
7. continuous numerical fields contain only explicitly supported quantitative values;
8. relationships between Binder, CAR, manufacturing process, and ABC combinations are supported by the source;
9. every identifier referenced by a row was assigned by a row above it;
10. each line of the output file is valid JSON with exactly the keys `table` and `data`.
