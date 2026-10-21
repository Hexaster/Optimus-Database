"""Versioned, additive PostgreSQL schema for staged scientific imports."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .identity import digest
from .schema_models import load_schema

MIGRATIONS = Path(__file__).resolve().parents[2] / "sql" / "migrations"
TABLES = ("binder", "car", "manufacturing", "abc_combination_db1", "evidence")
LOCK = 724019631  # Short transaction lock shared by migration/staging/publication.


# Map dotted evidence fields to SQL columns; entity references keep their familiar ID column names.
def column(name):
    # Entity foreign keys use their short ID column names; other dotted fields use underscores.
    if name in ("binder.binder_id", "car.car_id", "manufacturing.manufacturing_id"):
        return name.split(".")[1]
    return name.replace(".", "_")


# Find the primary-key field declared for this table in YAML.
def primary_key(table):
    # Collect items from load_schema().tables[table].items() only where v.get('key') == 'primary'.
    return next(k for k, v in load_schema().tables[table].items() if v.get("key") == "primary")


# Hash storage-relevant YAML properties while ignoring descriptive prose.
def contract_hash():
    keys = {"type", "nullable", "shape", "item_type", "item_schema", "allowed_values",
            "key", "references", "pattern", "preferred_unit"}

    # Recursively retain only schema properties that affect validation or database representation.
    def project(spec):
        # Collect items from spec.items() only where k in keys.
        return {k: ({n: project(v) for n, v in value.items()} if k == "item_schema" else value)
                for k, value in spec.items() if k in keys}

    # Build mapped values from load_schema().tables.items().
    return digest({t: {n: project(s) for n, s in f.items()}
                   for t, f in load_schema().tables.items()})


def migrate(conn):
    """Never drop or reinterpret legacy tables. Migration files are immutable."""
    # Keep these operations in one transaction so errors roll back the whole unit of work.
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        conn.execute("CREATE SCHEMA IF NOT EXISTS cart")
        conn.execute("""CREATE TABLE IF NOT EXISTS cart.schema_migration (
            version text PRIMARY KEY, checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now())""")
        # Apply migrations in version order under the shared transaction lock.
        for path in sorted(MIGRATIONS.glob("*.sql")):
            content = path.read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            old = conn.execute("SELECT checksum FROM cart.schema_migration WHERE version=%s",
                               (path.name,)).fetchone()
            # Already applied migrations are verified, not executed again.
            if old:
                # Even comment-only edits change an applied SQL checksum and must be rejected.
                if old[0] != checksum:
                    raise ValueError(f"Applied migration changed: {path.name}")
                continue
            conn.execute(content.decode("utf-8"))
            conn.execute("INSERT INTO cart.schema_migration(version,checksum) VALUES (%s,%s)",
                         (path.name, checksum))
        check_contract(conn)


# Refuse imports when the database contract and active YAML definitions disagree.
def check_contract(conn):
    row = conn.execute("SELECT schema_hash FROM cart.import_contract WHERE singleton").fetchone()
    # Stop with a diagnostic: YAML schema differs from the database import contract; add a migration
    # first.
    if not row or row[0] != contract_hash():
        raise ValueError("YAML schema differs from the database import contract; add a migration first.")
