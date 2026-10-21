# SQL walkthrough

There are two database layouts in this repository. The current importer uses the
`cart` schema and the ordered files in `sql/migrations/`. The retained legacy
initializer uses top-level `sql/*.sql` and separate schemas such as `binder`,
`car`, and `manufacturing`. They are separate workflows; running the current
migrations does not copy legacy records into `cart`.

## Current migration lifecycle

`cart_db.ingest_schema.migrate()` takes a transaction-scoped advisory lock,
creates the migration ledger, and checks each migration's SHA-256 checksum.
An already-applied file is skipped only when its bytes match the recorded hash.
A changed file is an error. New migrations run in filename order in the migration
transaction; a failure rolls back the transaction. The importer also checks the
storage-relevant YAML schema hash against `cart.import_contract`.

**Do not edit applied migration files, including comments or line endings.** This
walkthrough documents their functions and decisions without changing those bytes.
Schema changes belong in a new numbered migration together with the corresponding
YAML/importer changes.

## 001: scientific records, staging, and provenance

[`001_scientific_ingestion.sql`](../sql/migrations/001_scientific_ingestion.sql)
creates the initial current-schema tables:

| Tables | Purpose and constraints |
| --- | --- |
| `import_contract` | One row holding the schema hash; the true-only boolean primary key enforces the singleton. |
| `record` | Global UUID registry with a scientific table name. Each scientific table has a generated `record_kind` and a composite foreign key, preventing a UUID registered for one kind from being used as another kind. |
| `binder`, `car`, `manufacturing` | Typed scientific entities. Scalar enums use `CHECK`; nested values retain JSONB shapes. The application performs the deeper YAML validation. |
| `abc_combination_db1` | A unique binder/CAR/manufacturing tuple. All three owners must exist. |
| `evidence` | Source-specific observations with at least one direct entity owner. An optional combination reference must agree with every direct owner supplied. Dotted YAML field names become underscore-separated SQL columns. |
| `import_batch` | Original input text, filename, and a unique checksum for idempotent staging. |
| `import_context` | Named, checksummed source/context attachments associated with a batch. |
| `staged_record` | Original and normalized JSON, audit events, validation errors, and publication state for each input line. A published row must have a target UUID; an unpublished row must not. |
| `identity_feature` | Indexed candidate-retrieval values and fingerprints. A matching fingerprint retrieves candidates; it does not establish scientific identity. |
| `identity_decision` | Reviewer, reason, and explicit new/link decisions. New has no target; link has exactly one accepted or staged target, and cannot target itself. |
| `publication_log` | One publication mapping and decision explanation per staged assertion. |
| `entity_name`, `name_selection` | Source-attributed names and an audit of chosen display names. |

Foreign keys prevent dangling references. Ordinary indexes support source/owner
lookups; GIN indexes support JSON searches. Nullable checks permit absent values;
SQL constraints alone do not replace strict extraction validation.

### `cart.check_combination_evidence()` and its branches

This trigger function prevents evidence from naming a different binder, CAR, or
manufacturing process from its linked combination:

1. **Called for evidence insert/update:** if `NEW.combination_id` is absent,
   there is no combination to cross-check. Otherwise, inspect the referenced
   combination. Each non-null direct owner is compared with its corresponding
   combination owner. Any disagreement raises an exception and rejects the write.
2. **Called for a combination update:** inspect existing evidence referencing that
   combination. If any reported direct owner would disagree with the updated
   combination, raise an exception. This protects evidence already in the database.
3. **Neither check finds a conflict:** return `NEW`, allowing the row write to
   continue. A missing direct owner is not invented by this function; the table's
   separate owner-count constraint still applies.

The `EXISTS` queries scan for any conflicting row, and the three `OR` branches
check binder, CAR, and manufacturing independently. The evidence trigger runs
before every insert/update; the combination trigger runs before every update.
For example, evidence with binder B1 cannot reference a combination containing B2,
and changing a combination from B1 to B2 cannot invalidate existing B1 evidence.

## 002: historical manufacturing additions

[`002_manufacturing_steps.sql`](../sql/migrations/002_manufacturing_steps.sql)
adds nullable `process_step_status` and `harvest_steps` JSONB columns and advances
the contract hash. Existing rows keep unknown values; the migration does not infer
steps. These additions were subsequently retired by migration 003. They remain
here because migration history must replay consistently.

## 003: admission and identity review

[`003_admission_and_identity_review.sql`](../sql/migrations/003_admission_and_identity_review.sql):

- Copies manufacturing rows with either retired field populated into
  `retired_manufacturing_fields`, then drops those two live columns. Rows with both
  fields null need no archive entry.
- Replaces the vector-type constraint to also allow `CRISPR/Cas9+AAV定点插入`.
- Adds nullable identity status/details to staged records. Previously published
  binder/CAR/manufacturing rows are initialized as resolved; other rows are left
  untouched. An index targets non-resolved review states.
- Advances the schema contract hash to match the revised storage contract.

Publication state (`invalid`, `pending`, `published`) and identity status
(`resolved`, `unresolved`, `similar`, `conflict`) answer different questions.
The current Python publication policy can admit a valid ambiguous entity
independently and preserve its identity issue for review. Migration 003 supplies
the storage; `ingest.publish()` implements the policy.

## 004: remove completeness-only review warnings

[`004_resolve_unmatched_entities.sql`](../sql/migrations/004_resolve_unmatched_entities.sql)
changes only published binder/CAR/manufacturing assertions that are unresolved
and whose saved candidate list **and** normalization-flag list are explicitly
empty arrays. Rows with candidates, warnings, absent lists, other statuses, or
other table kinds do not qualify.

Qualifying rows become resolved, and their old details are retained under
`previous_identity_details`. The migration changes review metadata only: it does
not merge entities or rewrite scientific records or foreign keys. Missing fields
alone are not a duplicate-identity warning.

## Retained legacy SQL

`setup.sh` → `scripts/init_db.py` → `cart_db.db.apply_ddl()` loads the top-level
SQL scripts in filename order. This is historical setup, not the current tutorial.
The old smoke test and some parser mappings have drifted from these table shapes.

| File | Responsibility |
| --- | --- |
| `00_extensions.sql` | Extensions and namespaces. The optional vector-extension block catches any ordinary SQL error and continues with a notice; that notice does not distinguish a missing extension from permission or other failures. |
| `01_enums.sql` | QC severity enum. Duplicate-object errors are ignored so a repeated setup can reuse the existing type; this does not update enum members. |
| `02_core.sql` | Source registration, run tracking, model usage/cost records, daily totals, and historical merge logs. |
| `03_binder.sql` | Legacy binder entities and their source evidence. |
| `04_car.sql` | CAR backbones, module validation, and source evidence; see below. |
| `05_process.sql` | Legacy manufacturing protocols and their evidence. |
| `06_lit_patent.sql` | Literature/patent metadata and per-field evidence locations/quotations. |
| `07_db1_db2.sql` | Legacy ABC combinations and reserved prediction storage. These columns are not a prediction implementation. |
| `08_qc.sql` | QC findings and count views. The pass-rate numerator counts fixed/accepted findings; `NULLIF` returns null when there are no findings. KPI filters count the specified targets, selected sources, and trainable combinations. |
| `99_drop_all.sql` | Destructive legacy reset: drops the named schemas with `CASCADE`, including dependent objects. It does not reset the current `cart` schema. |

### `car.valid_modules(value)`

This SQL function checks that modules form a JSON array and uses `NOT EXISTS`
over `jsonb_array_elements` to reject any invalid element. Its predicate rejects:

- A non-object item, a missing/non-string `module_type`, or a type outside the
  listed vocabulary.
- A supplied `source_molecule` or `sequence` whose value is neither text nor JSON
  null. Missing optional members are allowed.
- A supplied, non-null `length` that is not numeric or whose text form is not a
  nonnegative integer. The regular expression rejects fractions and signs.

An empty array has no invalid elements and passes. `STRICT` returns SQL null for a
SQL-null argument, while the `modules NOT NULL` column constraint rejects that
input. Non-array JSON can also raise during array expansion; this function is
intended to reject it, not guarantee a false result for every malformed input.
`IMMUTABLE` and `PARALLEL SAFE` describe its lack of database/state dependencies.
