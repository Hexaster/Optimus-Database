# Retained legacy code

All legacy code is retained. This guide records what it does, its repository
callers, and the gaps a maintainer must resolve before treating it as a working
import path. “No callers” means none found in this repository; external use is
unknown. The current workflow is documented in the [README](../README.md).

## Older database and model helpers

| Files | Purpose and current connections | Limitations |
| --- | --- | --- |
| `setup.sh`, `Makefile`, `scripts/init_db.py`, top-level `sql/*.sql` | Earlier virtualenv/database bootstrap. `init_db.py` calls `db.apply_ddl()`; reset calls `db.drop_all()`. | Creates separate legacy schemas, not `cart`. Existing tables are not upgraded by `CREATE TABLE IF NOT EXISTS`. The Makefile defaults to a developer-specific Python path, and `make extract` references the absent `scripts/extract.py`. |
| `src/cart_db/db.py` | Connection/transaction management, SQL setup, batch tracking, and legacy KPI queries. Called by setup/smoke/storage/LLM code. | Requires the legacy tables. `drop_all()` removes the schemas named in `99_drop_all.sql` with `CASCADE`; it is not a current-schema reset. |
| `src/cart_db/storage.py` | Raw snapshot directories, file SHA-256 hashes, and source registration. Used by downloader registration and the old smoke test. | Registration writes `core.source_registry`; the current importer has its own batch/context provenance. |
| `src/cart_db/llm.py` | Earlier direct Anthropic client, budget checks, and token/cost recording. Used by the old smoke test and referenced by extraction tests. | Configured exchange-rate/model-price values are estimates, not a live pricing source. The current extraction runner invokes external agent CLIs instead. |
| `scripts/smoke_test.py` | Earlier checks for connectivity, source registration, old entities, and model access. | Several queries expect tables/columns that no longer match top-level SQL. It may call a model when credentials are present; it is not an offline test command. |
| `src/cart_db/extraction.py` | Document text loading and flattening of generated schema-model responses. | Tests still exercise these helpers. The current runner passes source documents directly to agent CLIs; the old extract_document and build_system_prompt APIs expected by some tests are absent. |

The SQL functions, constraints, and reset behavior are explained in the
[SQL walkthrough](sql_walkthrough.md). Retaining these helpers does not imply
that the old end-to-end smoke workflow passes.

## Structured-source parser stack

The intended flow is:

```text
SourceRegistry → downloader → data/raw/
Mapping YAML + raw files → scripts/parse.py → data/interim/
                                             records / rejects / manifest
```

The parser does not write PostgreSQL. Its `Record` objects carry separate values,
provenance, and null reasons for historical mapping targets such as
`binder.binder`. That is different from the current interchange envelope
`{"table": "binder", "data": {...}}`. An explicit, validated conversion would be
needed before using its output with the current importer.

| Module | What to read it for |
| --- | --- |
| `parsers/base.py` | Mapping loading, legacy DDL field introspection, source/null provenance, interim streams, schema checks, and the parser lifecycle. |
| `parsers/thera_sabdab.py` | CSV source handling, mono-/bispecific record expansion, heavy/light-chain assignment, and explicit handling of ambiguous targets. |
| `parsers/sabdab.py` | Summary-row parsing, source type/sequence metadata, and the unfinished structure-archive route. |
| `parsers/dotad.py` | Spreadsheet joins, source-column checks, metric conversion, and retaining ambiguous mappings as review problems. Uses `openpyxl` for Excel files; that optional dependency is absent from `requirements.txt`. |
| `scripts/parse.py` | Parser discovery, mapping selection, dry-run contract checks, output lifecycle, and diagnostic exit codes. |

`SourceParser.assign_uid()` raises `Undecided("Q2")`, and
`SourceParser.should_include()` raises `Undecided("Q4")`. These are deliberate
stops for unsettled identity/inclusion policies, not transient errors to retry.
The SAbDab structure route also has an explicit `NotImplementedError`. Mapping
contract checks can fail before any of those stops because the documents and
schemas have evolved separately. The historical `OPEN_QUESTIONS` text includes
old schema descriptions; it should not be read as the current database contract.

To inspect available parsers without importing records:

```bash
python scripts/parse.py --list
```

Read the corresponding `docs/Mapping/*.yaml` and `docs/SourceRegistry/*.yaml`
alongside each implementation. Do not suppress unresolved-policy exceptions to
make a run appear complete.

## Small helpers with no repository callers

- `src/cart_db/data_loader.py`: selects pandas CSV or Excel loading by filename
  suffix. It does not validate schema fields, provenance, or identity.
- `src/cart_db/parser/therasabdab.py`: loads CSV rows and applies direct/constant
  mapping fields to `NormalizedData`. Unsupported transformation methods are
  skipped. It is separate from the larger `parsers/thera_sabdab.py` stack and
  does not implement its source-specific rules.

These remain available for reference as requested. Any future removal should
account for external users and preserve the mapping/source documents independently.
