# Retained minimal mapping helper, separate from parsers/thera_sabdab.py. See docs/legacy_code.md.
import csv
from pathlib import Path
from typing import Any
from ..basemodel import NormalizedData

# Read the legacy CSV with BOM-aware headers; no current-schema validation is performed.
def load_thera_sabdab(path: str) -> list[dict]:
    # Close the file reliably, including when reading or writing raises an error.
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

# Apply only direct and constant legacy mappings, skipping unsupported transformation methods.
def map_record(
    record: dict[str, Any],
    mapping: dict[str, Any],
) -> list[NormalizedData]:
    outputs = []

    # Process each target from mapping['targets'] independently.
    for target in mapping["targets"]:
        data = {}

        # Process each field from target['fields'] independently.
        for field in target["fields"]:
            target_name = field["target"]
            source_name = field.get("source")
            method = field.get("method")

            # An unspecified mapping method copies the named source column directly.
            if method is None:
                value = record.get(source_name)

            # A constant mapping supplies the declared value without reading a source column.
            elif method == "constant":
                value = field.get("value")

            # Otherwise, skip this item and continue checking the remaining inputs.
            else:
                continue

            # Include reported values, including zero and False; omit only None.
            if value is not None:
                data[target_name] = value

        outputs.append(
            NormalizedData(
                table=target["table"],
                data=data,
            )
        )

    return outputs