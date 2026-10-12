"""Non-destructive batch normalization and duplicate review for extracted JSONL."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from uuid import NAMESPACE_URL, uuid5

from .agent_output import OutputError, _object, _unique_object
from .basemodel import NormalizedData
from .measurements import convert
from .schema_models import load_schema

# Explicit schema paths only. Never treat arbitrary prose as a sequence.
SEQUENCES = {
    "binder.scfv_sequence", "binder.heavy_chain.sequence",
    "binder.light_chain.sequence", "binder.fr_cdr_regions.sequence",
    "car.modules.sequence",
}
AA = frozenset("ACDEFGHIKLMNPQRSTVWY")
AA_EXTENDED = AA | frozenset("BXZJUO")
UNIT_ALIASES = {
    "μM": "uM", "µM": "uM", "μg/mL": "ug/mL", "µg/mL": "ug/mL",
    "sec": "s", "seconds": "s", "minute": "min", "minutes": "min",
    "hr": "h", "hrs": "h", "hours": "h", "days": "day",
    "℃": "°C", "degC": "°C", "s^-1": "1/s", "s−1": "1/s",
    "M^-1 s^-1": "1/(M*s)",
}


def canonical_sequence(value):
    """Remove ASCII layout whitespace and uppercase; reject annotations/gaps."""
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[ \t\r\n\f\v]", "", value).upper()
    return cleaned if cleaned and set(cleaned) <= AA_EXTENDED else None


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def normalize_record(table, data, rules=None):
    """Return normalized data and before/after events; input is never mutated.

    rules: field_aliases maps object paths to old->new keys; value_aliases maps
    full schema paths to exact old->new strings. Array paths omit indices.
    """
    rules = rules or {}
    schema = load_schema()
    events = []

    def event(path, reason, before, after):
        events.append(dict(path=path, reason=reason, before=before, after=after))

    def walk(obj, fields, schema_path, location):
        if not isinstance(obj, dict):
            raise OutputError(f"{location}: expected object")
        obj = deepcopy(obj)
        for old, new in rules.get("field_aliases", {}).get(schema_path, {}).items():
            if new not in fields:
                raise OutputError(f"{schema_path}: alias target not in schema: {new}")
            if old in obj and old != new:
                if new in obj and obj[new] != obj[old]:
                    raise OutputError(f"{location}: conflicting fields {old} and {new}")
                before = obj.pop(old)
                obj[new] = before
                event(f"{location}.{old}", "field_alias", before, {new: before})
        for name, spec in fields.items():
            value = obj.get(name)
            if value is None:
                continue
            key, loc = f"{schema_path}.{name}", f"{location}.{name}"
            if isinstance(value, str):
                alias = rules.get("value_aliases", {}).get(key, {}).get(value, value)
                if alias != value:
                    event(loc, "value_alias", value, alias)
                    value = obj[name] = alias
            if key in SEQUENCES:
                cleaned = canonical_sequence(value)
                if cleaned is None:
                    event(loc, "review_invalid_sequence", value, value)
                else:
                    if cleaned != value:
                        event(loc, "sequence_layout", value, cleaned)
                    obj[name] = cleaned
                    if set(cleaned) - AA:
                        event(loc, "review_ambiguous_or_nonstandard_residue", value, cleaned)
            elif spec.get("type") == "measurement":
                if not isinstance(value, dict):
                    raise OutputError(f"{loc}: expected measurement object")
                measurement = deepcopy(value)
                unit = measurement.get("unit")
                if isinstance(unit, str):
                    measurement["unit"] = UNIT_ALIASES.get(unit, unit)
                converted = convert(measurement, spec.get("preferred_unit"))
                if converted != value:
                    event(loc, "measurement_unit", value, converted)
                obj[name] = converted
                preferred = spec.get("preferred_unit")
                if preferred and converted.get("unit") != preferred:
                    event(loc, "review_missing_or_unconvertible_unit", value, converted)
            elif "item_schema" in spec:
                if spec.get("shape") == "object":
                    obj[name] = walk(value, spec["item_schema"], key, loc)
                else:
                    if not isinstance(value, list):
                        raise OutputError(f"{loc}: expected array")
                    obj[name] = [walk(item, spec["item_schema"], key, f"{loc}[{i}]")
                                 for i, item in enumerate(value)]
        # Strictly validate fields, enums and measurement structure after aliases.
        return _object(obj, fields, location)

    if table not in schema.tables:
        raise OutputError(f"unknown table: {table}")
    result = walk(data, schema.tables[table], table, table)
    return result, events


def candidate_groups(rows):
    """Indexed candidate discovery; no pairwise scan and no scientific merges."""
    schema = load_schema()
    groups = {}

    def add(table, basis, key, row_id):
        groups.setdefault((table, basis, _digest(key)), []).append(row_id)

    def certain(seq):
        return isinstance(seq, str) and bool(seq) and set(seq) <= AA

    for row in rows:
        table, data = row.table, row.data
        pk = next(n for n, s in schema.tables[table].items() if s.get("key") == "primary")
        row_id = data[pk]
        payload = {k: v for k, v in data.items() if k != pk}
        if any(v is not None and v != [] for v in payload.values()):
            add(table, "identical_normalized_payload", payload, row_id)
        if table == "binder":
            seq = data.get("scfv_sequence")
            if certain(seq):
                add(table, "exact_scfv_sequence", seq, row_id)
            heavy, light = data.get("heavy_chain") or {}, data.get("light_chain") or {}
            if all(certain(chain.get("sequence")) and chain.get("scope") == "variable_region"
                   for chain in (heavy, light)):
                add(table, "exact_vh_vl_pair", [heavy, light], row_id)
        if table == "car":
            modules = data.get("modules") or []
            if modules and all(certain(m.get("sequence")) for m in modules):
                add(table, "exact_ordered_backbone_modules", modules, row_id)
        if table in ("binder", "car", "manufacturing"):
            for name in [data.get("name"), *(data.get("aliases") or [])]:
                if isinstance(name, str) and name.strip():
                    add(table, "name_or_alias_only", name.strip().casefold(), row_id)
    return [dict(table=t, basis=b, fingerprint=h, record_ids=list(dict.fromkeys(ids)),
                 decision="review_required")
            for (t, b, h), ids in sorted(groups.items()) if len(set(ids)) > 1]


def process_batch(paths, rules=None):
    """Scope local IDs by input path, rewrite references, retain provenance."""
    schema = load_schema()
    rows, audit, provenance = [], [], []
    for path in sorted({Path(p).resolve() for p in paths}):
        document_rows, ids, seen = [], {}, {}
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            source = dict(input=str(path), line=line_no)
            try:
                item = json.loads(line, object_pairs_hook=_unique_object)
                if not isinstance(item, dict) or set(item) != {"table", "data"}:
                    raise OutputError("expected exactly table and data")
                table = item["table"]
                data, events = normalize_record(table, item["data"], rules)
                fields = schema.tables[table]
                pk = next(n for n, s in fields.items() if s.get("key") == "primary")
                old = data[pk]
                new = str(uuid5(NAMESPACE_URL, _dump([str(path), table, old])))
                provenance.append({**source, "table": table, "original_id": old,
                                   "normalized_id": new, "original_row": item})
                audit.extend({**source, **e} for e in events)
                # Only duplicate serialization with the SAME original ID is dropped.
                if (table, old) in seen:
                    if seen[table, old] != data:
                        raise OutputError(f"conflicting repeated ID {table}.{old}")
                    audit.append({**source, "reason": "duplicate_serialization",
                                  "normalized_id": new})
                    continue
                seen[table, old] = deepcopy(data)
                ids[table, old] = new
                data[pk] = new
                document_rows.append(NormalizedData(table=table, data=data))
            except (ValueError, TypeError, KeyError) as exc:
                raise OutputError(f"{path}:{line_no}: {exc}") from exc
        for row in document_rows:
            for name, spec in schema.tables[row.table].items():
                value = row.data[name]
                if spec.get("key") == "foreign" and value is not None:
                    target = spec.get("references", spec.get("to", "")).split(".")[0]
                    if (target, value) not in ids:
                        raise OutputError(f"{path}: unresolved {row.table}.{name}: {value}")
                    row.data[name] = ids[target, value]
            if row.table == schema.evidence_table:
                owners = [e for e in schema.entities if row.data[e.fk_column] is not None]
                if not owners:
                    raise OutputError(f"{path}: evidence must reference an entity")
                for entity in schema.entities:
                    if entity not in owners and any(v is not None for k, v in row.data.items()
                                                   if k.startswith(entity.kind + ".")):
                        raise OutputError(f"{path}: {entity.kind} fields without owner")
        rows.extend(document_rows)
    return rows, audit, provenance, candidate_groups(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="one or more extracted JSONL files")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--rules", type=Path, help="explicit JSON field/value alias rules")
    args = parser.parse_args()
    # Refuse to overwrite prior results; validate everything before creating outputs.
    if args.output_dir.exists():
        parser.error("output directory already exists; choose a new directory")
    rules = json.loads(args.rules.read_text(encoding="utf-8")) if args.rules else None
    rows, audit, provenance, candidates = process_batch(args.inputs, rules)
    args.output_dir.mkdir(parents=True)
    outputs = {"normalized.jsonl": [r.model_dump() for r in rows],
               "audit.jsonl": audit, "provenance.jsonl": provenance,
               "dedup_candidates.jsonl": candidates}
    for name, records in outputs.items():
        (args.output_dir / name).write_text("".join(_dump(r) + "\n" for r in records), encoding="utf-8")
    summary = dict(input_rows=len(provenance), output_rows=len(rows),
                   duplicate_serializations_removed=len(provenance) - len(rows),
                   review_events=sum(e["reason"].startswith("review_") for e in audit),
                   candidate_groups=len(candidates), scientific_merges_applied=0)
    (args.output_dir / "summary.json").write_text(_dump(summary) + "\n", encoding="utf-8")
    print(_dump(summary))


if __name__ == "__main__":
    main()
