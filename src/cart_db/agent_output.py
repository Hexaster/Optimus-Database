"""Validate and canonicalize agent JSONL before publishing it."""
from __future__ import annotations

from datetime import date
import json
import math
import re
from pathlib import Path
from uuid import uuid4

from .basemodel import NormalizedData
from .measurements import normalize_rows
from .schema_models import Measurement, load_schema


class OutputError(ValueError):
    """An output error with a JSONL line and field path."""


# Raise a validation error carrying the exact JSONL/field location.
def _fail(path, message):
    raise OutputError(f"{path}: {message}")


# Reject unknown keys and validate every declared field, filling nullable omissions.
def _object(value, fields, path):
    # A field object must be a dictionary before schema keys can be validated.
    if not isinstance(value, dict):
        _fail(path, "expected object")
    extra = value.keys() - fields.keys()
    # Reject undeclared fields instead of silently dropping potentially meaningful data.
    if extra:
        _fail(path, f"unknown fields: {', '.join(sorted(extra))}")
    # Build mapped values from fields.items().
    return {name: _value(value.get(name), spec, f"{path}.{name}")
            for name, spec in fields.items()}


# Validate one schema value without coercing types; recurse into nested objects and measurements.
def _value(value, spec, path):
    # Missing values are accepted only according to the field's nullability.
    if value is None:
        # A required field cannot be repaired by substituting null.
        if not spec.get("nullable", True):
            _fail(path, "required non-null field")
        return None
    kind = spec["type"]
    # Validate measurement structure and the numeric fields required by its kind.
    if kind == "measurement":
        # Build mapped values from ('value', 'lower', 'upper', 'error').
        fields = {
            "kind": {"type": "string", "nullable": False},
            **{key: {"type": "number"} for key in ("value", "lower", "upper", "error")},
            "unit": {"type": "string"},
            "raw": {"type": "string", "nullable": False},
        }
        result = _object(value, fields, path)
        # Use strict model validation so invalid measurement kinds cannot reach numeric checks.
        try:
            Measurement.model_validate(result, strict=True)
        # Attach the exact field path to measurement validation failures.
        except ValueError as exc:
            _fail(path, str(exc))
        used = {
            "single_value": {"value"}, "range": {"lower", "upper"},
            "image_estimated_range": {"lower", "upper"},
            "mean_with_standard_deviation": {"value", "error"},
            "mean_with_standard_error": {"value", "error"},
            "plus_minus_unspecified": {"value", "error"},
            "greater_than": {"lower"}, "greater_than_or_equal": {"lower"},
            "less_than": {"upper"}, "less_than_or_equal": {"upper"},
        }[result["kind"]]
        # Check required and forbidden numeric slots for the selected measurement kind.
        for key in ("value", "lower", "upper", "error"):
            # Reject both missing required components and extra incompatible components.
            if (result[key] is not None) != (key in used):
                _fail(f"{path}.{key}", f"inconsistent with kind={result['kind']}")
        # An uncertainty magnitude cannot be negative.
        if result["error"] is not None and result["error"] < 0:
            _fail(path, "error must be non-negative")
        # A reported range may collapse to a point but cannot reverse its endpoints.
        if result["kind"] == "range" and result["lower"] > result["upper"]:
            _fail(path, "lower must be <= upper")
        # An image-estimated range must have positive width, not a false point estimate.
        if result["kind"] == "image_estimated_range" and result["lower"] >= result["upper"]:
            _fail(path, "image-estimated lower must be < upper")
        return result
    # Nested JSON fields must follow their explicitly declared shape.
    if kind == "json":
        # Validate an object against its nested field definitions.
        if spec.get("shape") == "object":
            return _object(value, spec["item_schema"], path)
        # Reject an unspecified JSON shape instead of accepting arbitrary structures.
        if spec.get("shape") != "array":
            _fail(path, "schema must declare JSON shape")
        # Array-shaped fields must contain an actual list.
        if not isinstance(value, list):
            _fail(path, "expected array")
        # Validate structured array items with their own field paths.
        if "item_schema" in spec:
            # Build mapped values from enumerate(value).
            return [_object(item, spec["item_schema"], f"{path}[{i}]")
                    for i, item in enumerate(value)]
        # Build mapped values from enumerate(value).
        return [_value(item, {"type": spec["item_type"], "nullable": False},
                       f"{path}[{i}]") for i, item in enumerate(value)]
    types = {"string": (str,), "enum": (str,), "uuid": (str,), "date": (str,),
             "any": (str,), "boolean": (bool,), "integer": (int,),
             "number": (int, float)}
    # Exact type checks reject bool-as-number and numeric strings before arithmetic.
    if type(value) not in types[kind]:
        _fail(path, f"expected {kind}")
    # NaN and infinity are not valid finite scientific measurements.
    if kind in ("number", "integer") and not math.isfinite(value):
        _fail(path, "number must be finite")
    # An ID may be a local label, but an empty label cannot be referenced.
    if kind == "uuid" and not value.strip():
        _fail(path, "ID/reference must be a non-empty local identifier")
    # Validate dates by parsing and round-tripping the canonical ISO spelling.
    if kind == "date":
        # Convert parser failures into a field-specific output error.
        try:
            # Reject noncanonical date spellings even when the date parser accepts them.
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        # On ValueError, reject the input: expected YYYY-MM-DD.
        except ValueError:
            _fail(path, "expected YYYY-MM-DD")
    # Controlled-vocabulary values must appear in the active YAML enumeration.
    if "allowed_values" in spec and value not in spec["allowed_values"]:
        _fail(path, f"expected one of {spec['allowed_values']}")
    # Apply declared string patterns to the entire value.
    if spec.get("pattern") and re.fullmatch(spec["pattern"], value) is None:
        _fail(path, f"expected pattern {spec['pattern']}")
    return value


# Build a JSON object while rejecting repeated keys instead of silently taking the last value.
def _unique_object(pairs):
    result = {}
    # Examine JSON key pairs before the decoder could overwrite duplicate keys.
    for key, value in pairs:
        # Duplicate JSON keys are ambiguous and must fail validation.
        if key in result:
            raise OutputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def prepare_output(path: Path) -> str:
    """Return canonical JSONL; never modify the candidate on validation failure.

    Agent IDs are document-local reference labels, replaced with UUID4s only
    after validation. Row/list order and source text are preserved.
    YAML prose `check`/descriptions are not executable constraints; only explicit
    types, nullability, enums, patterns and Measurement structure are enforced.
    """
    schema = load_schema()
    rows = []
    ids = {}
    locations = []
    # Attach the candidate filename to file/encoding failures.
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    # On (OSError, UnicodeError), stop with a diagnostic: {path.name}: cannot read output: {exc}.
    except (OSError, UnicodeError) as exc:
        raise OutputError(f"{path.name}: cannot read output: {exc}") from exc
    # Validate each nonempty source line while keeping its original line number.
    for number, line in enumerate(lines, 1):
        # Blank lines contain no record and do not affect the ID map.
        if not line.strip():
            continue
        loc = f"line {number}"
        # Decode with duplicate-key detection before checking the row envelope.
        try:
            row = json.loads(line, object_pairs_hook=_unique_object)
        # Attach the JSONL line location to malformed JSON and duplicate-key errors.
        except (ValueError, OutputError) as exc:
            _fail(loc, str(exc))
        # Only table/data envelopes belong to the interchange format.
        if not isinstance(row, dict) or set(row) != {"table", "data"}:
            _fail(loc, "expected exactly table and data")
        table = row["table"]
        # Refuse unknown tables before selecting a field schema.
        if not isinstance(table, str) or table not in schema.tables:
            _fail(loc, "unknown table")
        fields = schema.tables[table]
        data = row["data"]
        # Require an object payload before generating its final primary key.
        if not isinstance(data, dict):
            _fail(loc, "data must be an object")
        # Unreferenced primary keys may be omitted; all supplied labels must be unique.
        pk = next(name for name, spec in fields.items() if spec.get("key") == "primary")
        data = dict(data)
        old_id = data.get(pk)
        new_id = str(uuid4())
        # Register supplied local IDs so later rows can reference them.
        if old_id is not None:
            _value(old_id, fields[pk], f"{loc}.{pk}")
            # One table/local-ID pair must identify exactly one input row.
            if (table, old_id) in ids:
                _fail(f"{loc}.{pk}", "duplicate primary ID")
            ids[table, old_id] = new_id
        data[pk] = new_id
        rows.append(NormalizedData(table=table, data=_object(data, fields, f"{loc}.{table}")))
        locations.append(loc)
    # Resolve references only after every row has registered its local ID.
    for row, loc in zip(rows, locations):
        # Check each declared field for an outgoing reference.
        for name, spec in schema.tables[row.table].items():
            value = row.data[name]
            # Ordinary fields and absent optional references need no ID rewrite.
            if spec.get("key") != "foreign" or value is None:
                continue
            target = spec.get("references", spec.get("to", "")).split(".")[0]
            # A nonempty reference must point to an entity present in this document.
            if (target, value) not in ids:
                _fail(f"{loc}.{name}", f"unresolved reference to {target}: {value}")
            row.data[name] = ids[target, value]
        # Evidence needs explicit owners independent of the row's measurement values.
        if row.table == schema.evidence_table:
            # Collect items from schema.entities only where row.data[entity.fk_column] is not None.
            owners = [entity for entity in schema.entities if row.data[entity.fk_column] is not None]
            # Reject evidence that does not directly identify any scientific entity.
            if not owners:
                _fail(loc, "evidence must reference at least one entity")
            # Check measurement ownership separately for each entity kind.
            for entity in schema.entities:
                # Measurements cannot be attributed to an entity whose reference is missing.
                if entity not in owners and any(
                    value is not None for name, value in row.data.items()
                    if name.startswith(entity.kind + ".")
                ):
                    _fail(loc, f"{entity.kind} measurements require its entity reference")
    normalized = normalize_rows(rows, schema)
    # Build mapped values from normalized.
    return "".join(json.dumps({"table": row.table, "data": row.data},
                              ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
                   for row in normalized)
