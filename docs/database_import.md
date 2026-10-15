# JSONL → PostgreSQL

The database ingestion path is `cart_db.ingest`. It creates a new `cart` schema
from versioned migrations in `sql/migrations/`; the older `binder`, `car`,
`manufacturing`, `core`, and `db1` schemas remain untouched. PostgreSQL 16 or
later is the tested target. No vector extension or language-model call is needed.

For the integrated PDF/XML → JSONL → database command and Chinese terminal output,
see [提取与入库操作说明](extraction_pipeline.md).

## Input and identity

Each nonblank JSONL line is `{ "table": ..., "data": ... }`, using the active
YAML schemas. Tables: `binder`, `car`, `manufacturing`, `abc_combination_db1`,
and `evidence`. Every input record needs a nonempty local ID.

- A local ID is scoped to the input batch, even if it looks like a UUID.
- References first resolve to records in that batch. An invalid local record
  cannot fall through to an existing database UUID of the same spelling.
- A reference absent from the batch may name an accepted database UUID of the
  correct table. Otherwise it fails QC.
- Accepted entities receive database UUIDs. Linking another source record reuses
  the accepted UUID; it does not replace the source record or existing fields.
- A file's SHA-256 checksum identifies the batch independently of its pathname.
  An identical file is staged only once. A changed/reformatted file is a new batch.

## Commands

Use the existing `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD`
configuration. Do not put passwords in command-line arguments. Run from the
repository root with `PYTHONPATH=src` (or install the package on your Python path).

```bash
# One-time additive schema initialization; reruns verify migration checksums.
PYTHONPATH=src python -m cart_db.ingest migrate

# Normalize and validate, then save source records into staging.
PYTHONPATH=src python -m cart_db.ingest stage path/to/data.jsonl \
  --context path/to/reasoning.md --context path/to/error_log.jsonl

# Use the batch_id returned by stage.
PYTHONPATH=src python -m cart_db.ingest publish BATCH_UUID
PYTHONPATH=src python -m cart_db.ingest status BATCH_UUID

# Inspect a pending entity and its supplied source context.
PYTHONPATH=src python -m cart_db.ingest inspect STAGE_UUID
PYTHONPATH=src python -m cart_db.ingest candidates STAGE_UUID

# After checking the original source, record ONE of these decisions.
PYTHONPATH=src python -m cart_db.ingest decide STAGE_UUID link \
  --target-id ACCEPTED_UUID --reviewer reviewer-name --reason 'Source-supported identity'
PYTHONPATH=src python -m cart_db.ingest decide STAGE_UUID link \
  --target-stage-id OTHER_STAGE_UUID --reviewer reviewer-name --reason 'Same source-defined entity'
PYTHONPATH=src python -m cart_db.ingest decide STAGE_UUID new \
  --reviewer reviewer-name --reason 'Source establishes a distinct entity'

# Publish again after decisions; already published records are not reinserted.
PYTHONPATH=src python -m cart_db.ingest publish BATCH_UUID

# Export the accepted five-table representation.
PYTHONPATH=src python -m cart_db.ingest export > accepted.jsonl
```

`--context` is repeatable and optional; omit absent files. It preserves supplied
reasoning, extraction exceptions, and postprocessing provenance/audit sidecars.
These are supporting material for review, not an automatically interpreted QC
certificate. Source documents remain external; keep their original locations.

`stage`, `status`, and `publish` display Chinese summaries. Add the global `--json`
option before the subcommand for machine-readable results with separate `invalid`,
`pending`, and `published` counts. A successful command does not mean every input row was
published. Invalid rows and raw input remain available for correction in a new
batch; unresolved dependants stay pending.

## Processing and automatic decisions

1. Preserve the input text and checksum. Normalize sequences and compatible
   units using the existing postprocessor, without scientific name aliases.
2. Validate schema fields, measurement structure, and references. Reject duplicate
   local IDs, including identical repetitions. Propagate invalid dependencies.
3. Store original and normalized records, normalization events, and QC errors.
4. Query indexed identity features across accepted and incoming records. Exact
   fingerprints retrieve candidates; actual values are compared before deciding.
   Partial-chain containment is an additional, review-only retrieval path.
5. Re-query under a short transaction lock at publication time. This prevents
   concurrent importers from independently creating the same exact identity.
6. Publish resolvable entities, map combination/evidence references, and check
   evidence/ABC consistency. Unexpected database errors roll back the entire
   publication transaction; staging remains available.

Admission and identity resolution are separate under `source-admission-v3`.
QC-valid records with incomplete or ambiguous identity are published as independent
source entities, so their combinations and evidence can be published too. Explicit
`identity_status` and `identity_details` track unresolved identity, similar protocols,
and red-flag conflicts independently of publication status. SQL/reference failures
still block the affected rows; no missing foreign key is fabricated.

Binders may link by a unique exact identifying name or source-confirmed alias,
provided known sequences do not conflict. Generic labels such as `anti-CD19 scFv`
are not identity proof. CAR backbone matching uses ordered module types and names;
Binder is separate under the current schema. Complete sequence matching remains.
Same names with conflicting corresponding known sequences raise red flags and never
auto-merge. Candidate source assertions are checked, not just the first snapshot.

Manufacturing compares selection input/output/method, activation method, gene-delivery
method, expansion container/mode, and culture duration. Delivery plus normalized
duration supports `similar` grouping only; identities remain separate. Ancillary
reagent, harvest/formulation/freezing details do not gate admission or exact matching.
Migration 003 archives and removes the two rejected schema additions. Historical raw
JSONL and source assertions remain preserved. See [中文规则](extraction_pipeline.md#制造工艺匹配).

`inspect`, `candidates`, and stored identity details support review; no Jev call is
performed. `decide` still applies only to unpublished rows. A reviewed merge executor
for already published entities is not yet implemented; do not delete duplicate
source entities or their observations manually.

ABC combinations reuse the same resolved A/B/C tuple. Each source's combination
attributes remain in staging; differing experimental-stage claims are not
overwritten or silently aggregated. Distinct evidence rows remain distinct,
including conflicting measurements. A reviewer can explicitly link an incoming
evidence record to an accepted observation after establishing that it is the same
observation; mapped entity/combination references must agree. Changed-file imports
do not automatically deduplicate observations based on equal values or citations.

## Where the information is stored

| Tables | Purpose |
|---|---|
| `cart.binder`, `car`, `manufacturing` | Accepted entity representations |
| `cart.abc_combination_db1`, `evidence` | Resolved combinations and separate observations |
| `cart.record` | Typed registry of accepted UUIDs |
| `cart.import_batch`, `import_context` | Original input, checksum, and supplied context |
| `cart.staged_record` | Source assertions, normalized values, errors, and mapping to accepted IDs |
| `cart.identity_feature` | Candidate lookup keys, including weak matches |
| `cart.identity_decision`, `publication_log` | Reviewed decisions and actual publication mappings |
| `cart.entity_name`, `name_selection` | Source-linked names and display-name decisions |
| `cart.schema_migration`, `import_contract` | Applied migration checksums and YAML contract |

Scientific tables have typed scalar/UUID columns and JSONB for measurements and
nested data. Evidence paths become SQL columns: `binder.kd` → `binder_kd`,
`binder.binder_id` → `binder_id`. Export restores the YAML field names.
YAML prose `check` expressions are not executable constraints; the importer uses
the existing explicit Python validation. SQL also enforces required fields,
top-level enum/JSON shapes, foreign keys, and evidence/ABC reference consistency.

The accepted entity representation is not a flattened union of all source claims.
New claims—including contradictions and additional details—are retained in
`staged_record.normalized` linked by `target_id`. Query those assertions when
comparing source-specific values; exporting accepted tables alone is not a full
provenance backup. Use PostgreSQL backup for the complete `cart` schema.

All collected names remain in `entity_name`, linked to the source staging row and
batch. Only binders currently have an `aliases` field in YAML; CAR/manufacturing
aliases live in this shared name table. The initial accepted `name` is a source
label, not an authoritative preferred name. A human or external Jev process can
select an existing name:

```bash
PYTHONPATH=src python -m cart_db.ingest select-name ENTITY_UUID 'Existing name' \
  --selector 'reviewer-or-model/version' --reason 'Reason for this display choice'
```

This command validates the selection and records it. It does not invoke Jev,
invent names, or change identity. Naming is not a publication prerequisite.

## Existing databases

Run the additive migration first; it does not copy or delete legacy records.
The importer searches `cart` records, not the obsolete legacy tables. Before
making it the authoritative database, inventory any populated legacy tables,
back them up, and convert their records into current-schema JSONL for staging.
Do not run the old reset command to upgrade a populated database.

Legacy VH/VL strings cannot silently become `variable_region` without scope
evidence. Scalar measurements cannot acquire guessed units, uncertainty, or
source quotations. Old split evidence records need explicit owner/provenance
mapping into the unified evidence table. Records lacking the required information
remain outside accepted storage until reconciled. No legacy migration was run on
the user's database; its contents have not been verified.

Future YAML contract changes require a new migration. Previously applied SQL
files are checksum-verified and must not be edited. The importer refuses a schema
contract mismatch rather than silently storing fields into an outdated layout.

## Small demo and tests

```bash
# Requires CREATE DATABASE on your development server. Creates a unique demo DB.
PYTHONPATH=src python scripts/demo_ingest.py

# Creates and removes its own randomly named test database on this server.
CART_TEST_DSN='host=localhost dbname=postgres user=YOUR_TEST_ROLE' \
  python -m pytest tests/test_ingest.py -q
```

The demo uses explicitly synthetic sequences and sources in
`examples/database_import/`. It leaves the new database for inspection.

| Import | Accepted binders | Accepted evidence | Pending rows |
|---|---:|---:|---:|
| Two initial binders and one observation | 2 | 1 | 0 |
| Same binder sequence, another name, new paper observation | 2 | 2 | 0 |
| VH-only binder compatible with both existing binders, plus its evidence | 2 | 2 | 2 |

The second paper's `0.003 uM` becomes `3 nM`; the first paper's `2 nM` observation
is retained separately. `Clone A` and `Clone-A scFv` refer to one accepted binder.
The incomplete record is not guessed into either existing binder.

Verified on 2026-10-13 with PostgreSQL 16.14: all 23 ingestion tests passed;
the full suite was 99 passed / 20 failed. The 20 failure names match the earlier
postprocessor baseline. Coverage includes transaction rollback, concurrent
publication, partial/multiple matches, conflicting linked source assertions,
reference mapping, reviewed observation links, repeat imports, and round trips.

The four existing `data/normalised/` data files were also staged in an isolated
database: 38, 56, 28, and 9 rows respectively were rejected by current-schema QC
(the three paper/patent files, followed by `thera_sabdab.jsonl`). They retain
legacy field names, scalar/old JSON representations, or obsolete table names.
No real-source records from those files were published. The successful demo is
synthetic and does not establish biological deduplication accuracy.

A missing identity field alone does not create an unresolved match. With no plausible
match or normalization review flag, the incoming entity is new and the current
matching check is resolved. This does not assert that its fields are complete.
