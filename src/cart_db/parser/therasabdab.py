import csv
from pathlib import Path
from typing import Any
from ..basemodel import NormalizedData

def load_thera_sabdab(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def map_record(
    record: dict[str, Any],
    mapping: dict[str, Any],
) -> list[NormalizedData]:
    outputs = []

    for target in mapping["targets"]:
        data = {}

        for field in target["fields"]:
            target_name = field["target"]
            source_name = field.get("source")
            method = field.get("method")

            if method is None:
                value = record.get(source_name)

            elif method == "constant":
                value = field.get("value")

            else:
                continue

            if value is not None:
                data[target_name] = value

        outputs.append(
            NormalizedData(
                table=target["table"],
                data=data,
            )
        )

    return outputs