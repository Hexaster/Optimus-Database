"""按 Schema 偏好统一测量单位；无法确定换算时保留来源值。"""
from __future__ import annotations

import argparse
from pathlib import Path

from .basemodel import NormalizedData
from .schema_models import ExtractionSchema, load_schema


# 同组单位通过基准值 x * scale + offset 换算，不跨组推算。
_UNITS = {
    "molarity": {"M": 1, "mM": 1e-3, "uM": 1e-6, "nM": 1e-9, "pM": 1e-12},
    "mass_concentration": {
        "g/L": 1, "mg/mL": 1, "ug/mL": 1e-3, "ng/mL": 1e-6, "pg/mL": 1e-9,
    },
    "time": {"s": 1, "min": 60, "h": 3600, "day": 86400},
    "off_rate": {"1/s": 1, "1/min": 1 / 60, "1/h": 1 / 3600},
    "on_rate": {"1/(M*s)": 1, "1/(M*min)": 1 / 60},
}
_CONVERSIONS = {
    unit: (group, scale, 0)
    for group, units in _UNITS.items() for unit, scale in units.items()
}
_CONVERSIONS.update({
    "K": ("temperature", 1, 0),
    "°C": ("temperature", 1, 273.15),
    "°F": ("temperature", 5 / 9, 273.15 - 32 * 5 / 9),
})


def convert(measurement: dict, preferred_unit: str | None) -> dict:
    """返回换算后的副本；raw 及未知单位保持不变。"""
    unit = measurement.get("unit")
    if not unit or not preferred_unit or unit == preferred_unit:
        return measurement.copy()
    source = _CONVERSIONS.get(unit.replace("μ", "u").replace("µ", "u"))
    target = _CONVERSIONS.get(preferred_unit.replace("μ", "u").replace("µ", "u"))
    if source is None or target is None or source[0] != target[0]:
        return measurement.copy()
    scale = source[1] / target[1]
    offset = (source[2] - target[2]) / target[1]
    result = {**measurement, "unit": preferred_unit}
    for name in ("value", "lower", "upper", "error"):
        if measurement.get(name) is not None:
            result[name] = measurement[name] * scale + (0 if name == "error" else offset)
    return result


def _normalize_fields(data: dict, fields: dict) -> dict:
    result = data.copy()
    for name, spec in fields.items():
        value = data.get(name)
        if value is None:
            continue
        if spec.get("type") == "measurement":
            result[name] = convert(value, spec.get("preferred_unit"))
        elif "item_schema" in spec:
            if spec.get("shape") == "object":
                result[name] = _normalize_fields(value, spec["item_schema"])
            else:
                result[name] = [_normalize_fields(item, spec["item_schema"]) for item in value]
    return result


def normalize_rows(
    rows: list[NormalizedData], schema: ExtractionSchema | None = None,
) -> list[NormalizedData]:
    schema = schema or load_schema()
    return [NormalizedData(table=row.table, data=_normalize_fields(
        row.data, schema.tables[row.table],
    )) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="原地归一化一份新抽取的 JSONL")
    path = parser.parse_args().path
    rows = [NormalizedData.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    output = "".join(row.model_dump_json() + "\n" for row in normalize_rows(rows))
    path.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
