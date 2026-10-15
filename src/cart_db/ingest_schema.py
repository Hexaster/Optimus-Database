"""Versioned, additive PostgreSQL schema for staged scientific imports."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .identity import digest
from .schema_models import load_schema

MIGRATIONS = Path(__file__).resolve().parents[2] / "sql" / "migrations"
TABLES = ("binder", "car", "manufacturing", "abc_combination_db1", "evidence")
LOCK = 724019631  # Short transaction lock shared by migration/staging/publication.


def column(name):
    if name in ("binder.binder_id", "car.car_id", "manufacturing.manufacturing_id"):
        return name.split(".")[1]
    return name.replace(".", "_")


def primary_key(table):
    return next(k for k, v in load_schema().tables[table].items() if v.get("key") == "primary")


def contract_hash():
    keys = {"type", "nullable", "shape", "item_type", "item_schema", "allowed_values",
            "key", "references", "pattern", "preferred_unit"}

    def project(spec):
        return {k: ({n: project(v) for n, v in value.items()} if k == "item_schema" else value)
                for k, value in spec.items() if k in keys}

    return digest({t: {n: project(s) for n, s in f.items()}
                   for t, f in load_schema().tables.items()})


def migrate(conn):
    """Never drop or reinterpret legacy tables. Migration files are immutable."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        conn.execute("CREATE SCHEMA IF NOT EXISTS cart")
        conn.execute("""CREATE TABLE IF NOT EXISTS cart.schema_migration (
            version text PRIMARY KEY, checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now())""")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            content = path.read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            old = conn.execute("SELECT checksum FROM cart.schema_migration WHERE version=%s",
                               (path.name,)).fetchone()
            if old:
                if old[0] != checksum:
                    raise ValueError(f"Applied migration changed: {path.name}")
                continue
            conn.execute(content.decode("utf-8"))
            conn.execute("INSERT INTO cart.schema_migration(version,checksum) VALUES (%s,%s)",
                         (path.name, checksum))
        check_contract(conn)


def check_contract(conn):
    row = conn.execute("SELECT schema_hash FROM cart.import_contract WHERE singleton").fetchone()
    if not row or row[0] != contract_hash():
        raise ValueError("YAML schema differs from the database import contract; add a migration first.")
