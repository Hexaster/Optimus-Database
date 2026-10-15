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


def _fail(path, message):
    raise OutputError(f"{path}: {message}")


def _object(value, fields, path):
    if not isinstance(value, dict):
        _fail(path, "expected object")
    extra = value.keys() - fields.keys()
    if extra:
        _fail(path, f"unknown fields: {', '.join(sorted(extra))}")
    return {name: _value(value.get(name), spec, f"{path}.{name}")
            for name, spec in fields.items()}


def _value(value, spec, path):
    if value is None:
        if not spec.get("nullable", True):
            _fail(path, "required non-null field")
        return None
    kind = spec["type"]
    if kind == "measurement":
        fields = {
            "kind": {"type": "string", "nullable": False},
            **{key: {"type": "number"} for key in ("value", "lower", "upper", "error")},
            "unit": {"type": "string"},
            "raw": {"type": "string", "nullable": False},
        }
        result = _object(value, fields, path)
        try:
            Measurement.model_validate(result, strict=True)
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
        for key in ("value", "lower", "upper", "error"):
            if (result[key] is not None) != (key in used):
                _fail(f"{path}.{key}", f"inconsistent with kind={result['kind']}")
        if result["error"] is not None and result["error"] < 0:
            _fail(path, "error must be non-negative")
        if result["kind"] == "range" and result["lower"] > result["upper"]:
            _fail(path, "lower must be <= upper")
        if result["kind"] == "image_estimated_range" and result["lower"] >= result["upper"]:
            _fail(path, "image-estimated lower must be < upper")
        return result
    if kind == "json":
        if spec.get("shape") == "object":
            return _object(value, spec["item_schema"], path)
        if spec.get("shape") != "array":
            _fail(path, "schema must declare JSON shape")
        if not isinstance(value, list):
            _fail(path, "expected array")
        if "item_schema" in spec:
            return [_object(item, spec["item_schema"], f"{path}[{i}]")
                    for i, item in enumerate(value)]
        return [_value(item, {"type": spec["item_type"], "nullable": False},
                       f"{path}[{i}]") for i, item in enumerate(value)]
    types = {"string": (str,), "enum": (str,), "uuid": (str,), "date": (str,),
             "any": (str,), "boolean": (bool,), "integer": (int,),
             "number": (int, float)}
    if type(value) not in types[kind]:
        _fail(path, f"expected {kind}")
    if kind in ("number", "integer") and not math.isfinite(value):
        _fail(path, "number must be finite")
    if kind == "uuid" and not value.strip():
        _fail(path, "ID/reference must be a non-empty local identifier")
    if kind == "date":
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            _fail(path, "expected YYYY-MM-DD")
    if "allowed_values" in spec and value not in spec["allowed_values"]:
        _fail(path, f"expected one of {spec['allowed_values']}")
    if spec.get("pattern") and re.fullmatch(spec["pattern"], value) is None:
        _fail(path, f"expected pattern {spec['pattern']}")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
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
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise OutputError(f"{path.name}: cannot read output: {exc}") from exc
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        loc = f"line {number}"
        try:
            row = json.loads(line, object_pairs_hook=_unique_object)
        except (ValueError, OutputError) as exc:
            _fail(loc, str(exc))
        if not isinstance(row, dict) or set(row) != {"table", "data"}:
            _fail(loc, "expected exactly table and data")
        table = row["table"]
        if not isinstance(table, str) or table not in schema.tables:
            _fail(loc, "unknown table")
        fields = schema.tables[table]
        data = row["data"]
        if not isinstance(data, dict):
            _fail(loc, "data must be an object")
        # Unreferenced primary keys may be omitted; all supplied labels must be unique.
        pk = next(name for name, spec in fields.items() if spec.get("key") == "primary")
        data = dict(data)
        old_id = data.get(pk)
        new_id = str(uuid4())
        if old_id is not None:
            _value(old_id, fields[pk], f"{loc}.{pk}")
            if (table, old_id) in ids:
                _fail(f"{loc}.{pk}", "duplicate primary ID")
            ids[table, old_id] = new_id
        data[pk] = new_id
        rows.append(NormalizedData(table=table, data=_object(data, fields, f"{loc}.{table}")))
        locations.append(loc)
    for row, loc in zip(rows, locations):
        for name, spec in schema.tables[row.table].items():
            value = row.data[name]
            if spec.get("key") != "foreign" or value is None:
                continue
            target = spec.get("references", spec.get("to", "")).split(".")[0]
            if (target, value) not in ids:
                _fail(f"{loc}.{name}", f"unresolved reference to {target}: {value}")
            row.data[name] = ids[target, value]
        if row.table == schema.evidence_table:
            owners = [entity for entity in schema.entities if row.data[entity.fk_column] is not None]
            if not owners:
                _fail(loc, "evidence must reference at least one entity")
            for entity in schema.entities:
                if entity not in owners and any(
                    value is not None for name, value in row.data.items()
                    if name.startswith(entity.kind + ".")
                ):
                    _fail(loc, f"{entity.kind} measurements require its entity reference")
    normalized = normalize_rows(rows, schema)
    return "".join(json.dumps({"table": row.table, "data": row.data},
                              ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
                   for row in normalized)
