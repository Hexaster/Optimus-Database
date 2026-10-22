---
name: extract-cart-data
description: Extract source-supported CAR-T entities and experimental evidence from papers, patents, database records, or internal documents into this project's YAML-defined JSONL format, with per-document data.jsonl, optional error_log.jsonl, and reasoning.md.
---

# CAR-T Document Extraction

## Figure artifact extension

When invoked by the current runner, its explicit overrides enable one additional image subagent independently of the structured-data cross-check setting. Follow `docs/figure_extraction.md`; retain `figures.jsonl` and `img/` alongside the data outputs. The older three-file-only wording below applies only when no runner figure override is supplied. The image subagent writes only figure artifacts, must not delegate further, and must finish before the coordinator reports completion.

## Image acquisition priority: API first, PDF fallback

For every relevant figure, first attempt to obtain the original or highest-quality image through an official source API or an asset URL returned by verified source metadata. Apply this order even when a local PDF is already available, and to text/Markdown inputs whose drawings are omitted. Reuse an already retrieved, verified API asset rather than downloading it again. Follow documented API routes and returned links; do not guess image URLs.

Verify the source identity (DOI, PMCID, patent publication/version, or equivalent), figure label, caption, panels, and readability. Prefer a complete original-resolution or vector asset over a thumbnail; API delivery alone does not establish higher quality. Preserve native resolution and avoid unnecessary resampling. If the API image is incomplete or less readable than the PDF, use the better complete source and explain the choice.

If an applicable API is unavailable, inaccessible, lacks the figure, or returns an unusable asset, retrieve or open the matching PDF and render the complete figure region, including axes, legends, and panel labels. Do not declare a figure unavailable merely because it is absent from the supplied Markdown/XML or local files. Mark it unavailable only after the applicable API and PDF routes have been attempted, or record the specific access/tool limitation that prevented an attempt. A main-text PDF cannot replace a missing supplementary figure.

Record the API/metadata route, original asset URL, retrieval date, source identifier, chosen asset and quality assessment, and any PDF fallback reason in the figure metadata or evidence summary. Retain source hashes and PDF page/crop coordinates where applicable. Do not invent provenance or mislabel an API image as a PDF crop. These acquisition rules also apply to the dedicated image subagent; local-only export helpers do not replace source retrieval.

## Workflow and execution scope

1. Read all current `docs/Schema/*.yaml` files. Active YAML fields, types, descriptions, and enums are authoritative; commented-out definitions are not fields.
2. Read the supplied document, including relevant tables, figures, captions, and supplied supplements. Follow the source-reading rules below.
3. Build a temporary inventory of source-described experiments and independent processes, then extract their distinct entities, combinations, and evidence into active schema fields. Follow Coverage and semantic review below.
4. Return to the source to check coverage, then check attribution and meaning. Update the inventory and draft for omissions found during review.
5. Write `data.jsonl`, `reasoning.md`, and any current-run `error_log.jsonl` in the document's output folder, normalize measurements, and complete the checks below. Apply explicit runner overrides as described under Output.

Use one agent by default. Do not spawn subagents or launch other agent processes unless the user or runner explicitly enables them (`--subagent true`). When enabled, follow the Independent extraction and cross-check section below. Subagents assigned a draft must not delegate further. Report whether independent cross-checking actually completed; ordinary single-agent extraction is not an incomplete run.

Follow the output-folder and runner-override rules below. Work only on the assigned document and its output files; `--workers` is managed by the runner, not by this skill. Keep rendered pages, downloads, and drafts in a unique temporary directory per run, or in a separate scratch subdirectory of the runner's private staging workspace when its override requires all writes there. Do not consult previous extraction outputs to fill source gaps. Do not modify schemas, code, or other documents' results during extraction.

## Animal and clinical evidence fields

Use the active `docs/Schema/Evidence.yaml` definitions for the exact keys, nested shapes, and field-level descriptions. The `animal.*` and `clinical.*` names are literal fields on an evidence row, not new tables. Nested item keys belong inside their declared JSON field; do not emit them as extra evidence columns. Use the existing source, entity, and combination relationships to retain attribution.

- `study_type` identifies the setting of the specific observation: `in_vitro`, `animal`, `clinical`, `computational`, or `other`. Split observations from different settings even when reported in one paper. A study's clinical phase does not make its accompanying animal experiments clinical evidence.
- `study_source` records journal, publication year, and clinical registry ID. Keep source identity in `source_id` and the evidence location in `citation`; a registration ID does not replace either.
- `animal.model` records the reported species, strain, sex, age, disease/tumor model, and immune status. `animal.study_groups` records each source-defined arm's sample size, comparator, baseline, intervention, follow-up, randomization, and blinding. Do not infer unreported model characteristics or study-design safeguards.
- `animal.efficacy_outcomes` stores attributable tumor burden, tumor inhibition, survival, or other animal efficacy observations. `animal.safety_outcomes` stores reported weight change, pathology, organ toxicity, death, or other animal safety observations. Do not impose human response criteria or clinical toxicity grades on animal results.
- `animal.cell_kinetics` stores animal expansion, distribution, and persistence, preserving tissue, assay, analyte, units, and time. Human kinetics belong in the clinical field.
### Clinical metrics and accepted inputs

The clinical fields follow the existing A/B/C pattern: each field has one defined quantity or property and an explicit type. Read the current YAML for exact keys and nested contracts. The old `clinical.cohorts`, `clinical.efficacy_outcomes`, `clinical.safety_outcomes`, and `clinical.cell_kinetics` containers are retired and must not be emitted. `clinical.trial_design` and `clinical.assessment_schedule` now accept strings only, not the former JSON structures.

- **Study and baseline.** Use `clinical.trial_phase` and `clinical.trial_design` for phase and design features only. `clinical.enrolled_count` and `clinical.infused_count` are reported integer counts, distinct from each result's analysis denominator. `clinical.patient_baseline` holds one identified patient/cohort's pretreatment characteristics and treatment background; no post-treatment results or follow-up narratives. Store a baseline observation once rather than copying it into every later specimen record.
- **One conditions object per evidence row.** Use `clinical.measurement_conditions` for the patient/cohort label, relevant analysis population, actual assessment time, assay, specimen, analyte, response criteria, MRD decision threshold, toxicity grading, safety observation window, treatment relatedness, AUC interval, detection limit and result-specific statistical qualifications. Populate only members relevant to that row's metric. Keep response standards in `response_criteria`, assay techniques in `method`, toxicity standards in `grading_system`, and source-specific endpoint definitions in `endpoint_definition`; do not repeat the same text across them. Keep citations in the existing `citation` field and actual units in the measurement object. Repeat the identifying conditions necessary to interpret an independent evidence row; do not assume that a different population, assay or protocol can be inherited solely from a shared DOI or product name.
- **Individual response versus population rates.** `clinical.response` accepts a reported individual response category, such as CR, CRi, PR or sCR. `clinical.mrd_status` accepts the explicit individual status; `clinical.mrd_level` accepts an actual quantitative MRD result. Never turn an individual response into a 100% rate or infer MRD negativity from CR. `clinical.orr`, `clinical.cr_rate`, `clinical.cri_rate`, `clinical.cr_or_cri_rate`, `clinical.pr_rate`, `clinical.mrd_negative_rate`, `clinical.mrd_negative_cr_rate`, `clinical.relapse_rate` and `clinical.disease_free_rate` accept only `{rate: measurement|null, numerator: integer|null, denominator: integer|null}` for that named endpoint. Keep a reported count/denominator when no rate is given, leaving rate null. Do not calculate missing ORR by adding CR and PR or derive counts from rounded rates.
- **Time-to-event.** `clinical.dor`, `clinical.pfs`, `clinical.efs` and `clinical.os` accept a source-reported duration measurement and/or an explicit `not_reached` or `not_estimable` status. Landmark survival percentages go in the corresponding `clinical.pfs_rate`, `clinical.efs_rate` or `clinical.os_rate`, with the landmark and time origin in the shared conditions. A patient follow-up duration is not automatically a survival duration.
- **Named toxicities.** `clinical.crs`, `clinical.icans` and `clinical.dlt` each accept only that event's reported grade, incidence/count, onset, duration/recovery and management. `clinical.ice_score` accepts the actual score and does not establish an ICANS grade by itself. A reported grade 0 is not an invented 0% event rate. Other events go into `clinical.cytopenias`, `clinical.infections` or `clinical.other_adverse_events` by the exact event name; do not also copy them into the dedicated CRS/ICANS/DLT fields. `clinical.ae` and `clinical.sae` accept overall patient incidence/count at that classification level, not a sum of individual events or overlapping grades. Keep grading system, window and relatedness in the one shared conditions object. Do not assume ASTCT 2019, CTCAE 5.0 or a 28-day DLT window.
- **Human cellular kinetics and biomarkers.** `clinical.cmax`, `clinical.tmax` and `clinical.auc` accept the actual reported peak, peak time and exposure measurements. Non-peak specimen results belong in `clinical.car_t_cell_count`, `clinical.car_t_ratio` or `clinical.transgene_level`; preserve the actual readout, denominator, unit, assay and specimen. `clinical.persistence` holds reported detectable duration and/or a qualitative detection observation; a single positive sample does not justify an inferred duration. Explicit qualitative group comparisons without metric values may use `clinical.kinetics_comparison`. Human specimen cytokine concentrations/detection observations belong in `clinical.cytokine_levels`, not in adverse-event fields or in-vitro manufacturing release fields. Do not duplicate an in-vivo result in `car.persistence` or another generic A/B/C result field.
- **Schedule.** `clinical.assessment_schedule` contains only the actual reported assessment names, visits/frequency and time origin. Observed result times belong in the conditions of their respective result rows. Do not copy the whole schedule or response protocol into each outcome or substitute example visits such as D28/M3/M6/M12.

Keep multiple named metrics together when they describe the same source observation and share the same conditions. Split evidence rows when patient/cohort, analysis population, denominator, assessment time, assay or other distinguishing conditions differ. Preserve numerator/denominator per named rate field; different endpoints need not share a denominator. Shared context is written once per row, not once inside every metric.

For animal outcome and kinetics arrays, continue using one item per source-supported group, analysis population, endpoint, assessment time and other distinguishing conditions. Match `group_id` to the source-defined context; it is not a platform UUID. Preserve reported numerator/denominator and use `source_locator` for item-level attribution. Numerical values use the shared measurement structure.

Use animal fields only for animal observations and clinical fields only for human clinical observations. Unreported or inapplicable nullable fields remain null. Examples and reference-document conventions are not study data. Do not repeat the same observation solely because it is reported in a caption, abstract or supplementary table: consolidate only when source identity, patient/population, event, time, conditions and statistical scope establish that it is the same observation, retaining every source location and unresolved conflict. In particular, a patient's same CRS/ICANS event grade repeated beside later kinetic samples is not a new safety event at every sampling date.

### Return source figures for animal results

When an animal evidence row cites or relies on a source figure or panel, return a copy of that original figure in `{out_dir}/animal_figures/` so reviewers can inspect the visual evidence alongside the structured result. Include only figures that support populated `animal.efficacy_outcomes`, `animal.safety_outcomes`, or `animal.cell_kinetics`; do not include figures used only for human, in-vitro, manufacturing, or construct evidence. Prefer the publisher/PMC figure asset or supplied supplement image and copy it without editing. For a PDF-only source, render and crop the complete relevant figure from its page at readable resolution; keep panel labels, axes, legends, and scale bars. Do not redraw, annotate, or estimate missing figure content. If a figure is unavailable or cannot be isolated reliably, leave the image out and record the limitation in `reasoning.md` or `error_log.jsonl` as appropriate.

Use a simple unique filename per figure, with its original extension (`.png`, `.jpg`, `.tif`, `.webp`, `.svg`, or `.pdf`). Add `{out_dir}/animal_figures/manifest.json` with this structure, mapping each copied file to the final one-based physical JSONL row numbers of animal evidence it supports:

```json
{
  "figures": [
    {
      "file": "Figure_2.png",
      "source_locator": "Figure 2A-C",
      "evidence_rows": [4, 5]
    }
  ]
}
```

Do not copy the full article PDF as a substitute for a figure. If no relevant animal figure is available, omit the `animal_figures/` directory entirely. Keep unrelated downloads and scratch files outside this directory; the runner publishes this directory only after checking the manifest and its links to evidence rows.

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
  - Actually inspect downloaded images or rendered PDF pages with an image-viewing tool, together with captions and panel labels. Read tables with row/column headers, units, and footnotes; read sequence listings with their SEQ ID identifiers. A successful download alone does not establish readable evidence. Prefer explicitly reported values. When labels are absent, estimate pixel-based ranges under the Image-based measurement ranges rules below. SD/SEM must be supported by text or legends.
  - Keep downloads in temporary locations, or within the runner's private staging directory when required by its output override. Record source-page and asset URLs, retrieval date, inspected figure/table/page/SEQ ID locations, and affected fields in `reasoning.md`; retain the original source identity in evidence rows and use schema-supported citation fields for locations.
  - Stop once the needed material is obtained or applicable resource routes below have been checked and a relevant alternative is exhausted. A landing-page 403 or browser challenge does not establish that its images or supplements are unavailable. Use bounded request timeouts, respect the run budget and access controls, and do not repeatedly retry a blocked endpoint. If network/image tools are unavailable, access fails, identity is uncertain, or content remains unreadable, retain readable evidence and log only the unresolved affected fields/records using existing exception categories. State attempted URLs and failure reasons in `reasoning.md`; do not report successfully recovered content as still missing.
- **PDFs:** when text extraction loses table alignment, image content, or sequence characters, render and inspect the affected pages. A caption or URL alone does not count as viewing a figure.
- Read measurements with their row/column headers, units, footnotes, groups, and panels. Use explicitly reported numbers when available; otherwise use a traceable pixel-based range when the image supports it. Identify SD/SEM from the source, not the appearance of error bars.
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

Keep the inventory open to additions during extraction and review. Record only combinations of conditions actually reported; do not generate a Cartesian product of doses, time points, or groups. Distinguish inaccessible source content from information not reported, using the source-recovery rules above. Within each experiment, inventory separately reported observations by source location/panel, group, time/round, sample or donor identity when given, observation level (representative sample, individual sample/donor, or aggregate statistic), and readout/denominator. Include numerical labels in representative plots as well as summary panels. These are observation entries within an experiment, not automatically independent experiments. Preserve unknown identities and levels as unknown; do not infer a donor identity from panel order.

### Coverage review: what was missed?

After drafting, return to source sections, Methods, captions, and tables rather than checking only populated fields or the initial inventory. For source-reported information with an active schema destination, check:

- **Operations:** subject, steps, reagent names and product identifiers, amounts or concentrations, times, temperatures, equipment, and post-processing.
- **Experiments:** experimental and control groups, doses or E:T ratios, time points, tissues, sample sizes, replicates, and readouts.
- **Observation coverage:** map every inventoried representative, individual, and aggregate observation to its own attributable output row/readout or an explicit gap. A group mean or estimated range does not cover separately reported individual values, even if they fall within that range. Conversely, individual values do not replace a reported aggregate. Revisit any observation marked duplicate and verify that it is the same observation under the identity rule below.

Do not replace explicit parameters or enumerated groups with a broad summary. An experiment without exact numerical results may support an image-estimated range under the rules below, or qualitative or method information where an active field permits it; do not force that information into a numerical or unrelated field. Facts already fully stored in the correct location need not be duplicated for coverage. Do not invent unreported checklist items.

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

**Evidence:** for the same ABC combination, keep multiple readouts from the same experiment, conditions, and observation identity in one evidence row, even when they appear in different figure panels. Separate rows when the combination, experiment, conditions, or observation identity differ, including groups, target cells, E:T ratios, time points, stimulation rounds, individual samples/donors, and representative versus aggregate observations. Shared figure numbers or entity IDs alone do not establish observation identity. Never transfer a measurement between entities or observations without explicit source support.

**Observation identity and deduplication:** merge repeated reporting only when the source establishes the same experiment, subject/sample or aggregate population, conditions, readout/denominator, and statistical scope. A representative sample, each reported individual donor, and an aggregate statistic are distinct observations: retain each source-supported observation with an active schema destination. Similar values, numerical overlap, a shared group label, or membership in the same experiment do not make them duplicates. Do not omit representative values merely because they are not group statistics. When text and a figure repeat the same observation, store it once with the relevant source locations; different observations are not a source conflict merely because their values differ.

Use existing fields to preserve these distinctions: state the source-supported observation level, sample/donor label when given, group and time/round in `applicable_scenario`; retain the measurement’s statistical meaning and gate/denominator in `raw`, and the exact panel/table location in `citation`. Do not invent schema keys or donor labels. If the source does not identify a representative sample, distinguish it by its source location and leave its sample identity unspecified. Separate evidence rows do not imply independent biological replicates: retain a source-established relationship to the same experiment/cohort in the context, do not increase sample size, and do not calculate a new mean or pooled statistic from representative and aggregate records. Reuse the appropriate entity and combination IDs.

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

### Image-based measurement ranges

When a quantitative plot lacks an explicit value for an attributable group and condition, attempt pixel-based estimation if an active measurement field matches the plotted readout. An absent number label alone is not a reason to retain only experimental conditions.

- Prefer an explicit value in text, tables, data labels or supplied numerical data for the same observation identity and readout. Do not duplicate it with an estimate from its illustration. This does not allow an explicit representative/individual value to replace a different aggregate observation, or an aggregate value to replace representative/individual observations; retain each under the observation-identity rule above. Inspect the source image and caption; use the highest usable resolution available, preserving panel identity. Enlarging a low-resolution image does not create extra precision.
- Establish the group, time/round, readout, unit and axis scale. Calibrate against at least two readable ticks in the relevant axis segment, recording their numeric values and pixel coordinates. Interpolate in data space for linear axes and log space for logarithmic axes; respect reversed axes, multipliers and axis breaks. If calibration or group attribution is unreliable, leave the affected value null and document the specific limitation.
- Identify a pixel interval covering the bar's result edge or the relevant marker/curve at the specified x position. Account for line thickness, image resolution, overlap and calibration uncertainty; round bounds outward at a precision supported by the figure. Do not use an arbitrary fixed percentage margin, infer points hidden by overlap, extrapolate beyond the plotted domain, or estimate unreadable flow-cytometry percentages from dot density. Interpolation needed to map pixels onto an axis is allowed; inventing unreported experimental time points is not.
- Store `kind: image_estimated_range`, with `lower < upper`, source `unit`, and `value`/`error` null. This interval expresses reading precision, not biological variation, a donor range, SD, SEM or a confidence interval. Estimate the plotted central value where applicable, not the span of its error bars; do not fabricate an error term. A mean ± SD explicitly reported elsewhere stays a mean ± SD.
- In `raw`, label the value as a pixel-based estimate and name the figure/panel, group, time/round, readout and estimated range. Use `citation` for the source location. In `reasoning.md`, link each estimate to its final row/field and record the source image identity and dimensions, any crop coordinates, axis/tick calibration, result pixel interval, mapping and outward rounding. Shared calibration may be recorded once with the affected rows listed. Recheck the mapped range against the image; ordinary successful estimation is not an extraction exception.
- Preserve the plotted metric. A remaining-cell count is not a killing percentage, intracellular cytokine positivity is not a secretion concentration, and survival is not automatically lysis. If the active schema has no destination for the plotted readout, report that gap rather than place an estimate in an unrelated field. Do not treat digitization as permission to derive new biological metrics.

## Conflicts and provenance

For conflicting measurements with clear identity and context, retain the attributable values in separate evidence rows with exact source locations and log the conflict. Do not select a preferred value or alter the source. When identity or attribution is uncertain, retain unambiguous data and leave affected nullable fields `null`; omit a record only if its identity cannot be established.

Use actual source identifiers such as DOI, PMCID, patent accession, or internal document ID. Never invent them. In `citation`, include the source reference and available page, section, table, figure, or panel location for the evidence. Do not invent page numbers. Interpret `contrary_evidence` from source-supported context: it identifies evidence contrary to the main conclusion, not merely a negative result, a weaker result, a control group, or disagreement between extraction drafts.

## Output

### One folder per document

Use `data/normalised/<source-stem>/` for each document. If the user overrides the output root, keep the same per-document folder structure under that root. Each document has the structured extraction files and validated figure artifacts managed by the runner:

```text
<source-stem>/
  data.jsonl
  original.jsonl
  reasoning.md
  error_log.jsonl       # only when exceptions occur
  figures.jsonl         # validated source-figure inventory
  img/                  # validated figure crops
  animal_figures/       # only when animal-result figures are available
    manifest.json
    Figure_2.png
  source_manifest.json  # runner checksums and provenance
```

Always write `data.jsonl` and `reasoning.md`, including when extraction returns no records. The runner publishes normalized and original JSONL, the figure inventory and image directory, the source manifest, optional exceptions, and `animal_figures/` only when validated animal-result figures are available. Keep independent drafts, review material, downloads, rendered pages, and other scratch artifacts outside the final document folder. Do not create additional per-document reports, alternate data formats, or timestamped copies. On a rerun, refresh these final artifacts for the current extraction; do not append new data or reasoning to a previous run. Start the exception log fresh for this run, removing a previous generated `error_log.jsonl` if the current run has no exceptions.

### Reasoning summary

Write `reasoning.md` as a concise evidence and decision summary, not a transcript of private internal reasoning. Include:

* the source identity and content inspected, including any unavailable content;
* consequential extraction decisions: entity and experimental-group attribution, schema mappings, record grouping, exclusions, and handling of ambiguity or conflicts;
* source locations supporting those decisions (page, section, table, figure, or panel), linked to table, row number, and field name when applicable; final record IDs may also be used when they will not be rewritten by the runner;
* a compact coverage table with one row per inventory entry: experiment/process or eligible entity and source location; covered/partially covered/not stored; output table, row number, and field, or the reason for a gap. Use one-based physical line numbers in final `data.jsonl`, refreshing references after edits. Summarize parameter coverage within the entry rather than listing every parameter separately;
* whether the coverage review, semantic review, independent cross-check (when enabled), and final validation completed, plus any limitations.

Summarize final decisions and their supporting evidence; do not reproduce step-by-step internal deliberation or the agents' private reasoning. Ordinary extraction rationale belongs here. Actual exceptions still belong in `error_log.jsonl`; this summary does not replace the exception log or add fields to the schema.

### Runner overrides

When the runner supplies a private staging directory, write `data.jsonl`, `reasoning.md`, optional `error_log.jsonl`, and animal-result figure copies plus their manifest directly there; do not add a `<source-stem>/` subfolder. The runner publishes validated artifacts into the final per-document folder. Follow its explicit overrides for write locations, identifiers, nullable-field completion, and normalization. If it assigns final UUIDs, reference records in `reasoning.md` by table, row number, and field name so references survive publication. If it performs normalization, preserve source values and leave conversion to the runner; report validation or normalization as pending until verified rather than claiming the runner has already completed them. The UUID and normalization instructions below apply when those steps have not been delegated to the runner.

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
- Verify normalization succeeded (or was explicitly delegated to the runner), and only current-run exceptions remain. Verify the final document folder contains the runner-managed structured data and figure bundle, optional `animal_figures/` only when validated copies are available, and no scratch files. Check that separately reported representative, individual and aggregate observations remain distinguishable in output and coverage notes, and that the non-empty reasoning summary reflects the final records and actual cross-check/validation status.
- Count written rows by table and exceptions from the files. Report counts, unresolved failures, and whether extraction was single-agent or independently cross-checked.
