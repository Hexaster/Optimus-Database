# Optimus Database

The database component of **Optimus**, focused on collecting, validating, and
storing CAR-T research data. It turns source documents into traceable records for
binders, CAR backbones, manufacturing protocols, and experimental evidence for use
by downstream Optimus applications.

## How it works

```text
PDF / XML / Markdown → extraction agent → validated JSONL
                                               ↓
                              normalization and quality checks
                                               ↓
                              staging → identity checks → PostgreSQL
                                                              ↓
                                                browser / JSONL export
```

The current PostgreSQL `cart` schema contains five scientific tables:

| Table | Contents |
| --- | --- |
| `binder` | A: antigen-binding domains, names, and sequences |
| `car` | B: CAR backbones with ordered modules |
| `manufacturing` | C: manufacturing methods and culture conditions |
| `abc_combination_db1` | Links between A, B, and C entities |
| `evidence` | Source-specific observations, measurements, and citations |

Supporting tables retain original inputs, normalization changes, validation
errors, and identity decisions. A possible match is not an automatic merge:
valid but ambiguous entities can be published separately and marked for review.
Measurements from different sources remain separate observations.

## Code structure

| Path | Responsibility |
| --- | --- |
| `docs/Schema/` | YAML field definitions used by validation/model generation; DBML diagrams |
| `src/cart_db/schema_models.py`, `agent_output.py` | Extraction models and strict JSONL validation |
| `src/cart_db/measurements.py`, `postprocess.py` | Unit/sequence normalization, audit output, duplicate candidates |
| `src/cart_db/identity.py`, `manufacturing.py` | Entity identity and manufacturing similarity rules |
| `src/cart_db/ingest.py`, `ingest_schema.py` | Staging, reference mapping, publication, export, migrations |
| `src/cart_db/figures.py`, `artifacts.py`, `scripts/extract_figures.py` | Figure rendering, inventory validation, and artifact checksums |
| `src/cart_db/pipeline.py`, `extraction_progress.py` | Resume checks, extraction/import coordination, progress reporting |
| `src/cart_db/browser.py`, `web/` | Local read-only HTTP API and browser interface |
| `scripts/` | Command-line entry points and demonstrations |
| `src/cart_db/downloaders/`, `docs/SourceRegistry/` | Source-specific downloads and configuration |
| `parsers/`, `scripts/parse.py` | Retained, incomplete structured-source parsers (see limitations below) |
| `docs/Mapping/` | Structured-source mapping specifications |
| `sql/migrations/` | Versioned migrations for the current `cart` schema |
| `examples/` | Synthetic JSONL examples and optional normalization rules |
| `tests/` | Unit tests and optional PostgreSQL integration tests |
| `data/` | Raw sources and generated results |
| `.claude/skills/extract-cart-data/` | Instructions read by the extraction agent |

Start with `scripts/run_extraction_agent.py`, then `pipeline.py`,
`agent_output.py`, and `ingest.py`. Read `identity.py` to understand the difference
between retrieving a candidate, establishing identity, and publishing a record.

## Tutorial

Run commands from the repository root. Use Python 3.11 or later and PostgreSQL
(the supplied Docker configuration uses PostgreSQL 17). Extraction also requires
an installed, authenticated agent CLI; normalization and import need no model.

### 1. Set up Python and configuration

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

# Preserve an existing configuration.
test -f .env || cp .env.example .env
```

Edit `.env` to set `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD`.
Keep credentials local. Existing environment variables take precedence over `.env`.
Replace the example's model/provider placeholders when configuring extraction.
There is no package-install configuration, so keep `PYTHONPATH` set when running
`python -m cart_db.…`.

### 2. Try normalization without a database

```bash
python -m cart_db.postprocess \
  examples/post_extraction/paper.jsonl \
  examples/post_extraction/patent.jsonl \
  --output-dir data/postprocessed/first-run
```

This synthetic example converts five input rows into four output rows by removing
one repeated serialization. Both entities and both source observations remain.
Outputs include `normalized.jsonl`, `provenance.jsonl`, `audit.jsonl`,
`dedup_candidates.jsonl`, and `summary.json`. Choose a new output directory for
another run; existing directories are rejected. This command neither merges
scientific entities nor writes to PostgreSQL.

### 3. Start PostgreSQL and import JSONL

Use the supplied server or an existing database where your role can create the
`cart` schema:

```bash
docker compose up -d db
docker compose exec db pg_isready -U cart -d cart
# Continue once the server reports that it accepts connections.
python -m cart_db.ingest migrate
python -m cart_db.ingest stage examples/database_import/01_existing.jsonl
```

For Docker, `PGPASSWORD` must match the database password. Changing `.env` does
not reset the password in an existing Docker volume.

Each JSONL line has the form `{"table": "binder", "data": {...}}`; see
[`examples/database_import/`](examples/database_import/) for complete inputs.
Copy the batch UUID printed by `stage` into `BATCH_ID`:

```bash
BATCH_ID='paste-the-batch-uuid-here'
python -m cart_db.ingest status "$BATCH_ID"
python -m cart_db.ingest publish "$BATCH_ID"
python scripts/browse_database.py
```

Open **http://127.0.0.1:8765** to browse entities, evidence, source records, and
identity-review details. The browser is read-only and does not run migrations.

`stage` saves valid and rejected rows. `publish` commits resolvable rows: check the
published, pending, and invalid counts. Use `inspect STAGE_UUID` and
`candidates STAGE_UUID` to investigate individual rows. Reimporting identical file
contents reuses the same batch.

```bash
python -m cart_db.ingest export > accepted.jsonl
```

Export includes accepted scientific records, not all provenance. A complete
backup also needs the PostgreSQL staging/audit tables and original documents.
For a synthetic end-to-end demonstration, run `python scripts/demo_ingest.py`.
It requires `CREATE DATABASE` permission and retains its new database for inspection.

### 4. Extract a source document

The runner supports Claude Code, Codex, Kimi Code, and ZCode. Install and
authenticate the chosen CLI separately. Preview a run first:

```bash
python scripts/run_extraction_agent.py \
  --agent claude \
  --file data/sample/record-0001_PMC5087292_Oncoimmunology2016.pdf \
  --import-db --dry-run
```

Remove `--dry-run` to invoke the agent and import results. Omit `--import-db` to
produce extraction artifacts without database import. Use `--model` for an explicit model, `--dir` for a folder, and
`--workers` for concurrent documents. See `--help` for timeout, validation-repair,
and budget options. Budget enforcement depends on the selected backend.

Results default to `data/normalised/<agent>/<model-or-default>/<document-stem>/`:
`original.jsonl`, validated `data.jsonl`, `reasoning.md`, `figures.jsonl`, `img/`,
and `source_manifest.json`, plus optional error logs. Database runs add an import
report. Matching source/schema/artifact checksums allow extraction reuse; failed
drafts remain available for diagnosis. Existing outputs without the figure contract
need `--figures-only` to add images or `--force` for a full rerun. Keep source
documents and referenced local image assets for verification.

## Other tools and limitations

- `scripts/download.py REGISTRY --list` lists download routes. Downloads produce
  source files and manifests; `--register` uses the older `core.source_registry`
  table. Downloader `--dry-run` behavior varies: some routes still fetch metadata
  or write planning files.
- `setup.sh`, top-level `sql/*.sql`, `scripts/init_db.py`, `scripts/smoke_test.py`,
  and `db.py`/`storage.py`/`llm.py` belong to the earlier database workflow.
  They are not the setup path for this tutorial. The old smoke test can call a
  model when credentials exist. The Makefile has a machine-specific Python default
  and `make extract` references a missing script.
- `parsers/` and `scripts/parse.py` retain the earlier SAbDab, Thera-SAbDab, and
  DOTAD parser stack. Its interim format differs from current JSONL; unresolved
  inclusion/ID policies intentionally stop parsing, and the SAbDab structure path
  is unfinished. DOTAD also needs `openpyxl`, which is not in `requirements.txt`.
  The older `src/cart_db/data_loader.py` and `src/cart_db/parser/therasabdab.py`
  helpers currently have no repository callers. All are retained for reference;
  see the [legacy code guide](docs/legacy_code.md).
- Current migrations update `cart`; they do not convert legacy records.
  **Never edit applied migrations**, even for comments: their checksums are
  verified. See the [SQL walkthrough](docs/sql_walkthrough.md).
- A reviewed merge operation for already published entities is not implemented.
  Successful validation and candidate similarity still require scientific review.
- `.pipeline-demo/` contains local database state and extraction outputs when
  present. It is not cache; `demo_pipeline.py cleanup` deletes those demo assets.

## Development

```bash
python -m pytest -q

# Optional database integration tests; use a dedicated development server.
# This role must be allowed to create and remove temporary test databases.
CART_TEST_DSN='host=localhost dbname=postgres user=YOUR_TEST_ROLE' \
  python -m pytest -q
```

Without `CART_TEST_DSN`, database integration tests are skipped. Some existing
tests still expect removed extraction APIs and older schema fields, so the full
suite is not currently green. Use `docs/Schema/` and the current importer as the
active contract.

Each extraction also delegates figure capture to one dedicated image subagent.
This is independent of `--subagent true`, which enables two structured-data
extraction drafts. Result figures are saved under `<document>/img/`, with captions,
page/crop provenance and missing-asset explanations in `figures.jsonl`. The source
manifest hashes every published image. Image bytes stay on disk; database context
stores the inventory and manifest.

To add images to an existing checksummed extraction without changing its data:

```bash
python scripts/run_extraction_agent.py --file data/sample/record-0001_PMC5087292_Oncoimmunology2016.pdf \
  --out-dir YOUR_EXISTING_OUTPUT_ROOT --figures-only
```

Use the same output root that contains the existing document folder. Backfills
require a valid `source_manifest.json`; an unmanifested extraction needs a full
`--force` rerun. See the [image extraction workflow](docs/figure_extraction.md)
for helper commands, artifact format, and subagent instructions. The sample pilot
is documented in [data/figure_sample_test/review.md](data/figure_sample_test/review.md).

More detail: [extraction](docs/extraction_pipeline.md),
[database import](docs/database_import.md),
[post-extraction processing](docs/post_extraction.md), and
[browser](docs/database_browser.md). Those documents also contain historical
results; this README describes the current entry points.
