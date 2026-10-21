"""Non-destructive batch normalization and duplicate review for extracted JSONL."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from uuid import NAMESPACE_URL, uuid5

from .agent_output import OutputError, _object, _unique_object, _value
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
    "hr": "h", "hrs": "h", "hours": "h", "days": "day", "weeks": "week",
    "℃": "°C", "degC": "°C", "s^-1": "1/s", "s−1": "1/s",
    "M^-1 s^-1": "1/(M*s)",
}


def canonical_sequence(value):
    """Remove ASCII layout whitespace and uppercase; reject annotations/gaps."""
    # When isinstance(value, str) is empty or false, leave the result unresolved instead of
    # inventing a value.
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[ \t\r\n\f\v]", "", value).upper()
    # Use cleaned when cleaned and set(cleaned) <= AA_EXTENDED; otherwise use None.
    return cleaned if cleaned and set(cleaned) <= AA_EXTENDED else None


# Produce stable UTF-8 JSON for fingerprints and deterministic output artifacts.
def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


# Hash a canonical candidate value without discarding the source record.
def _digest(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def normalize_record(table, data, rules=None):
    """Return normalized data and before/after events; input is never mutated.

    rules: field_aliases maps object paths to old->new keys; value_aliases maps
    full schema paths to exact old->new strings. Array paths omit indices.
    """
    # Use an empty mapping when rules is missing or empty.
    rules = rules or {}
    schema = load_schema()
    events = []

    # Append a field-level before/after audit event for normalization or required review.
    def event(path, reason, before, after):
        events.append(dict(path=path, reason=reason, before=before, after=after))

    # Apply explicit aliases and recurse through declared fields, preserving an audit of each
    # change.
    def walk(obj, fields, schema_path, location):
        # Stop with a diagnostic: {location}: expected object.
        if not isinstance(obj, dict):
            raise OutputError(f"{location}: expected object")
        obj = deepcopy(obj)
        # Apply only field aliases explicitly configured for this object path.
        for old, new in rules.get("field_aliases", {}).get(schema_path, {}).items():
            # A rename must target an active schema field.
            if new not in fields:
                raise OutputError(f"{schema_path}: alias target not in schema: {new}")
            # Move an old key only when it is present and actually changes the key.
            if old in obj and old != new:
                # Conflicting old/new values require review rather than overwriting either
                # assertion.
                if new in obj and obj[new] != obj[old]:
                    raise OutputError(f"{location}: conflicting fields {old} and {new}")
                before = obj.pop(old)
                obj[new] = before
                event(f"{location}.{old}", "field_alias", before, {new: before})
        # Visit declared fields in schema order and preserve field-level audit paths.
        for name, spec in fields.items():
            value = obj.get(name)
            # Do not infer values for missing optional fields.
            if value is None:
                continue
            key, loc = f"{schema_path}.{name}", f"{location}.{name}"
            # Value aliases apply to exact text values, not nested objects or approximate names.
            if isinstance(value, str):
                alias = rules.get("value_aliases", {}).get(key, {}).get(value, value)
                # Record only real alias changes in the audit.
                if alias != value:
                    event(loc, "value_alias", value, alias)
                    value = obj[name] = alias
            # Only declared sequence fields receive sequence-layout normalization.
            if key in SEQUENCES:
                cleaned = canonical_sequence(value)
                # Preserve invalid sequence text and request review rather than guessing a repair.
                if cleaned is None:
                    event(loc, "review_invalid_sequence", value, value)
                # For a valid sequence, audit any layout changes and retain its cleaned
                # representation.
                else:
                    # Record whitespace/case changes while retaining the original sequence in the
                    # audit.
                    if cleaned != value:
                        event(loc, "sequence_layout", value, cleaned)
                    obj[name] = cleaned
                    # Ambiguous/nonstandard residues stay present but require review.
                    if set(cleaned) - AA:
                        event(loc, "review_ambiguous_or_nonstandard_residue", value, cleaned)
            # Measurement normalization is separate from ordinary text aliases.
            elif spec.get("type") == "measurement":
                # Reject scalar measurements before any conversion arithmetic.
                if not isinstance(value, dict):
                    raise OutputError(f"{loc}: expected measurement object")
                # Reject malformed inputs before arithmetic can coerce their types.
                # Keep the original shape for accurate before/after audit events.
                _value(value, spec, loc)
                measurement = deepcopy(value)
                unit = measurement.get("unit")
                # Normalize only recognized unit spellings; keep unknown units verbatim.
                if isinstance(unit, str):
                    measurement["unit"] = UNIT_ALIASES.get(unit, unit)
                converted = convert(measurement, spec.get("preferred_unit"))
                # Audit conversions only when they actually change the measurement.
                if converted != value:
                    event(loc, "measurement_unit", value, converted)
                obj[name] = converted
                preferred = spec.get("preferred_unit")
                # A missing or incompatible unit remains a review issue, not an inferred conversion.
                if preferred and converted.get("unit") != preferred:
                    event(loc, "review_missing_or_unconvertible_unit", value, converted)
            # Recurse only through nested structures declared by YAML.
            elif "item_schema" in spec:
                # Object-shaped fields use one recursive walk.
                if spec.get("shape") == "object":
                    obj[name] = walk(value, spec["item_schema"], key, loc)
                # Array-shaped nested fields must be lists; normalize each item against its item
                # schema.
                else:
                    # Reject a non-list value before walking an array-shaped field.
                    if not isinstance(value, list):
                        raise OutputError(f"{loc}: expected array")
                    # Build mapped values from enumerate(value).
                    obj[name] = [walk(item, spec["item_schema"], key, f"{loc}[{i}]")
                                 for i, item in enumerate(value)]
        # Strictly validate fields, enums and measurement structure after aliases.
        return _object(obj, fields, location)

    # Stop with a diagnostic: unknown table: {table}.
    if table not in schema.tables:
        raise OutputError(f"unknown table: {table}")
    # Preserve retired manufacturing fields in source/audit while excluding them from the active
    # schema.
    if table == "manufacturing" and isinstance(data, dict):
        data = deepcopy(data)
        # Handle each explicitly retired field without deleting unrelated metadata.
        for field in ("process_step_status", "harvest_steps"):
            # Only emit a retirement audit event when the original field was supplied.
            if field in data:
                event(f"manufacturing.{field}", "retired_field_preserved_in_source", data.pop(field), None)
    result = walk(data, schema.tables[table], table, table)
    return result, events


def candidate_groups(rows):
    """Indexed candidate discovery; no pairwise scan and no scientific merges."""
    schema = load_schema()
    groups = {}

    # Group row IDs by table, matching basis, and value fingerprint for later review.
    def add(table, basis, key, row_id):
        groups.setdefault((table, basis, _digest(key)), []).append(row_id)

    # Allow exact sequence candidates only for nonempty, unambiguous amino-acid strings.
    def certain(seq):
        # Only nonempty, unambiguous amino-acid strings contribute exact sequence candidate keys.
        return isinstance(seq, str) and bool(seq) and set(seq) <= AA

    # Index each normalized row without merging scientifically distinct IDs.
    for row in rows:
        table, data = row.table, row.data
        # Collect items from schema.tables[table].items() only where s.get('key') == 'primary'.
        pk = next(n for n, s in schema.tables[table].items() if s.get("key") == "primary")
        row_id = data[pk]
        # Collect items from data.items() only where k != pk.
        payload = {k: v for k, v in data.items() if k != pk}
        # Do not create an identical-payload group from entirely empty content.
        if any(v is not None and v != [] for v in payload.values()):
            add(table, "identical_normalized_payload", payload, row_id)
        # Build binder sequence candidates separately from weak name candidates.
        if table == "binder":
            seq = data.get("scfv_sequence")
            # Only an unambiguous scFv can support an exact scFv candidate key.
            if certain(seq):
                add(table, "exact_scfv_sequence", seq, row_id)
            # Apply the explicit fallbacks to missing/empty values while retaining any reported
            # nonempty values.
            heavy, light = data.get("heavy_chain") or {}, data.get("light_chain") or {}
            # VH/VL pairs require certain sequences and explicitly reported variable-region scope.
            if all(certain(chain.get("sequence")) and chain.get("scope") == "variable_region"
                   for chain in (heavy, light)):
                add(table, "exact_vh_vl_pair", [heavy, light], row_id)
        # CAR candidate keys describe ordered backbone modules.
        if table == "car":
            # Use an empty list when data.get('modules') is missing or empty.
            modules = data.get("modules") or []
            # Require a sequence for every module; preserve type, boundaries, and order.
            if modules and all(certain(m.get("sequence")) for m in modules):
                # Build mapped values from modules.
                signature = [{"module_type": m["module_type"], "sequence": m["sequence"]}
                             for m in modules]
                add(table, "exact_ordered_backbone_modules", signature, row_id)
        # Names retrieve entity candidates, not experimental observations.
        if table in ("binder", "car", "manufacturing"):
            # Include every reported primary name and alias in weak retrieval.
            for name in [data.get("name"), *(data.get("aliases") or [])]:
                # Skip blank and non-text candidate labels.
                if isinstance(name, str) and name.strip():
                    add(table, "name_or_alias_only", name.strip().casefold(), row_id)
    # Collect items from sorted(groups.items()) only where len(set(ids)) > 1.
    return [dict(table=t, basis=b, fingerprint=h, record_ids=list(dict.fromkeys(ids)),
                 decision="review_required")
            for (t, b, h), ids in sorted(groups.items()) if len(set(ids)) > 1]


def process_batch(paths, rules=None):
    """Scope local IDs by input path, rewrite references, retain provenance."""
    schema = load_schema()
    rows, audit, provenance = [], [], []
    # Process unique absolute source paths deterministically; paths scope the generated UUIDs.
    for path in sorted({Path(p).resolve() for p in paths}):
        document_rows, ids, seen = [], {}, {}
        # Keep original line positions in provenance even when blank lines are skipped.
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # Blank lines do not create output records.
            if not line.strip():
                continue
            source = dict(input=str(path), line=line_no)
            # Attach the source path and line to malformed-record errors.
            try:
                item = json.loads(line, object_pairs_hook=_unique_object)
                # Stop with a diagnostic: expected exactly table and data.
                if not isinstance(item, dict) or set(item) != {"table", "data"}:
                    raise OutputError("expected exactly table and data")
                table = item["table"]
                data, events = normalize_record(table, item["data"], rules)
                fields = schema.tables[table]
                # Collect items from fields.items() only where s.get('key') == 'primary'.
                pk = next(n for n, s in fields.items() if s.get("key") == "primary")
                old = data[pk]
                new = str(uuid5(NAMESPACE_URL, _dump([str(path), table, old])))
                provenance.append({**source, "table": table, "original_id": old,
                                   "normalized_id": new, "original_row": item})
                # Build mapped values from events.
                audit.extend({**source, **e} for e in events)
                # Only duplicate serialization with the SAME original ID is dropped.
                if (table, old) in seen:
                    # Repeated local IDs may collapse only when their normalized payloads are
                    # identical.
                    if seen[table, old] != data:
                        raise OutputError(f"conflicting repeated ID {table}.{old}")
                    audit.append({**source, "reason": "duplicate_serialization",
                                  "normalized_id": new})
                    continue
                seen[table, old] = deepcopy(data)
                ids[table, old] = new
                data[pk] = new
                document_rows.append(NormalizedData(table=table, data=data))
            # On (ValueError, TypeError, KeyError), stop with a diagnostic: {path}:{line_no}: {exc}.
            except (ValueError, TypeError, KeyError) as exc:
                raise OutputError(f"{path}:{line_no}: {exc}") from exc
        # Rewrite references after all document-local IDs have been assigned.
        for row in document_rows:
            # Inspect every schema field for an outgoing reference.
            for name, spec in schema.tables[row.table].items():
                value = row.data[name]
                # Only populated foreign keys require a new UUID mapping.
                if spec.get("key") == "foreign" and value is not None:
                    target = spec.get("references", spec.get("to", "")).split(".")[0]
                    # Cross-document or missing local targets cannot be silently invented.
                    if (target, value) not in ids:
                        raise OutputError(f"{path}: unresolved {row.table}.{name}: {value}")
                    row.data[name] = ids[target, value]
            # Evidence must preserve explicit ownership through ID rewriting.
            if row.table == schema.evidence_table:
                # Collect items from schema.entities only where row.data[e.fk_column] is not None.
                owners = [e for e in schema.entities if row.data[e.fk_column] is not None]
                # Reject observations without any direct entity owner.
                if not owners:
                    raise OutputError(f"{path}: evidence must reference an entity")
                # Check ownership independently for binder, CAR, and manufacturing measurements.
                for entity in schema.entities:
                    # Entity-specific measurement values require that entity's direct reference.
                    if entity not in owners and any(v is not None for k, v in row.data.items()
                                                   if k.startswith(entity.kind + ".")):
                        raise OutputError(f"{path}: {entity.kind} fields without owner")
        # All foreign keys must be rewritten before comparing linked records,
        # including when evidence precedes its combination in the input file.
        combinations = {row.data["combination_id"]: row.data for row in document_rows
                        if row.table == schema.combination_table}
        # Check evidence/combination consistency after all forward references are rewritten.
        for row in document_rows:
            # Rows without a linked combination need no combination-consistency check.
            if row.table != schema.evidence_table or row.data["combination_id"] is None:
                continue
            combination = combinations[row.data["combination_id"]]
            # Compare each supplied evidence owner with the corresponding A/B/C member.
            for entity in schema.entities:
                value = row.data[entity.fk_column]
                # Reject contradictory owners instead of selecting one source of identity.
                if value is not None and value != combination[entity.id_column]:
                    raise OutputError(
                        f"{path}: evidence {row.data['record_id']}: {entity.fk_column} "
                        f"conflicts with combination {row.data['combination_id']}: "
                        f"{value} != {combination[entity.id_column]}"
                    )
        rows.extend(document_rows)
    return rows, audit, provenance, candidate_groups(rows)


# Validate all input documents before writing a new normalization/audit output directory.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="one or more extracted JSONL files")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--rules", type=Path, help="explicit JSON field/value alias rules")
    args = parser.parse_args()
    # Refuse to overwrite prior results; validate everything before creating outputs.
    if args.output_dir.exists():
        parser.error("output directory already exists; choose a new directory")
    # Use json.loads(args.rules.read_text(encoding='utf-8')) when args.rules; otherwise use None.
    rules = json.loads(args.rules.read_text(encoding="utf-8")) if args.rules else None
    rows, audit, provenance, candidates = process_batch(args.inputs, rules)
    args.output_dir.mkdir(parents=True)
    # Build mapped values from rows.
    outputs = {"normalized.jsonl": [r.model_dump() for r in rows],
               "audit.jsonl": audit, "provenance.jsonl": provenance,
               "dedup_candidates.jsonl": candidates}
    # Write each output stream separately so normalized data and audit/provenance remain
    # distinguishable.
    for name, records in outputs.items():
        # Build mapped values from records.
        (args.output_dir / name).write_text("".join(_dump(r) + "\n" for r in records), encoding="utf-8")
    # Build mapped values from audit.
    summary = dict(input_rows=len(provenance), output_rows=len(rows),
                   duplicate_serializations_removed=len(provenance) - len(rows),
                   review_events=sum(e["reason"].startswith("review_") for e in audit),
                   candidate_groups=len(candidates), scientific_merges_applied=0)
    (args.output_dir / "summary.json").write_text(_dump(summary) + "\n", encoding="utf-8")
    print(_dump(summary))


# Run the command only when invoked as a script, not when imported by tests or other modules.
if __name__ == "__main__":
    main()
