"""Independent review probes for commit 09cd59bb.

Run from the workspace after archiving that commit to /tmp/fosun-dedup-review:
  PYTHONPATH=/tmp/fosun-dedup-review/src REVIEW_REPO=/tmp/fosun-dedup-review \
    /home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest \
    -o pythonpath=/tmp/fosun-dedup-review/src \
    review_artifacts/dedup-20261012/test_review.py -q

Failures assert desired behavior and reproduce findings, not implementation fixes.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cart_db.agent_output import OutputError
from cart_db.measurements import convert
from cart_db.postprocess import normalize_record, process_batch


def row(table, **data):
    return {"table": table, "data": data}


def write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def evidence(**extra):
    return {"record_id": "e", "source_type": "literature", "source_id": "S", **extra}


@pytest.mark.parametrize("unit", ["nM", "uM"])
@pytest.mark.parametrize("kind,field", [
    ("single_value", "value"), ("greater_than", "lower"),
    ("less_than", "upper"), ("mean_with_standard_deviation", "error"),
])
def test_boolean_measurements_rejected_before_conversion(unit, kind, field):
    m = {"kind": kind, field: True, "unit": unit, "raw": "invalid boolean"}
    if field == "error":
        m["value"] = 2
    with pytest.raises(OutputError):
        normalize_record("evidence", evidence(**{"binder.kd": m}))


@pytest.mark.parametrize("metadata", [{"source_molecule": "CD8 alpha"}, {"length": 4}])
def test_backbone_sequence_candidate_survives_optional_metadata(tmp_path, metadata):
    modules = [{"module_type": "hinge", "sequence": "ACDE"}]
    path = write(tmp_path / "car.jsonl", [
        row("car", car_id="c1", modules=modules),
        row("car", car_id="c2", modules=[{**modules[0], **metadata}]),
    ])
    _, _, _, groups = process_batch([path])
    assert any(g["basis"] == "exact_ordered_backbone_modules" for g in groups)


def five_tables():
    return [
        row("binder", binder_id="b1"),
        row("car", car_id="c1", modules=[]),
        row("manufacturing", manufacturing_id="m1"),
        row("abc_combination_db1", combination_id="abc", binder_id="b1",
            car_id="c1", manufacturing_id="m1"),
        row("evidence", **evidence(combination_id="abc", **{
            "binder.binder_id": "b1", "car.car_id": "c1", "manufacturing.manufacturing_id": "m1"})),
    ]


def test_all_five_tables_references_and_forward_references(tmp_path):
    rows, _, prov, _ = process_batch([write(tmp_path / "all.jsonl", five_tables()[::-1])])
    tables = {r.table: r.data for r in rows}
    assert len(prov) == 5
    assert tables["evidence"]["combination_id"] == tables["abc_combination_db1"]["combination_id"]
    for table, key in [("binder", "binder_id"), ("car", "car_id"), ("manufacturing", "manufacturing_id")]:
        assert tables["evidence"][f"{table}.{key}"] == tables[table][key]
        assert tables["abc_combination_db1"][key] == tables[table][key]


def test_combination_entity_mismatch_rejected(tmp_path):
    rows = five_tables()
    rows.insert(0, row("binder", binder_id="b2"))
    rows[-1]["data"]["binder.binder_id"] = "b2"
    with pytest.raises(OutputError):
        process_batch([write(tmp_path / "mismatch.jsonl", rows)])


@pytest.mark.parametrize("bad", [
    row("binder"), row("binder", binder_id=""),
    row("binder", binder_id="b", unknown="x"),
    row("binder", binder_id="b", aliases="wrong shape"),
    row("binder", binder_id="b", heavy_chain={"sequence": "ACDE", "scope": "invented"}),
    row("evidence", **evidence()),
    row("evidence", **evidence(**{"binder.binder_id": "missing"})),
    row("evidence", **evidence(**{"binder.binder_id": "b", "car.activation_readout": "wrong owner"})),
])
def test_invalid_batch_rejected(tmp_path, bad):
    with pytest.raises(OutputError):
        process_batch([write(tmp_path / "bad.jsonl", [row("binder", binder_id="b"), bad])])


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "keys.jsonl"
    path.write_text('{"table":"binder","data":{"binder_id":"b","name":"a","name":"b"}}\n')
    with pytest.raises(OutputError, match="duplicate JSON key"):
        process_batch([path])


@pytest.mark.parametrize("source,target,value,expected", [
    ("L", "mL", 2, 2000), ("µL", "mL", 500, .5),
    ("cells/L", "cells/mL", 2000, 2), ("cells/uL", "cells/mL", 2, 2000),
    ("EU/L", "EU/mL", 2000, 2), ("°C/s", "°C/min", 2, 120),
    ("°C/h", "°C/min", 60, 1), ("°F", "°C", 32, 0),
])
def test_conversion_scales(source, target, value, expected):
    result = convert({"value": value, "unit": source, "raw": "original"}, target)
    assert result["value"] == pytest.approx(expected)
    assert result["raw"] == "original"


@pytest.mark.parametrize("kind,values", [
    ("single_value", {"value": 2}), ("range", {"lower": 1, "upper": 2}),
    ("mean_with_standard_deviation", {"value": 2, "error": .3}),
    ("mean_with_standard_error", {"value": 2, "error": .3}),
    ("plus_minus_unspecified", {"value": 2, "error": .3}),
    ("greater_than", {"lower": 2}), ("greater_than_or_equal", {"lower": 2}),
    ("less_than", {"upper": 2}), ("less_than_or_equal", {"upper": 2}),
])
def test_measurement_semantics_preserved(kind, values):
    m = {"kind": kind, **values, "unit": "uM", "raw": "source text"}
    data, _ = normalize_record("evidence", evidence(**{"binder.kd": m}))
    result = data["binder.kd"]
    assert result["kind"] == kind and result["raw"] == m["raw"]
    for key, value in values.items():
        assert result[key] == pytest.approx(value * 1000)


def test_complete_vh_vl_pair_candidates(tmp_path):
    chains = {"heavy_chain": {"sequence": "evq lv", "scope": "variable_region"},
              "light_chain": {"sequence": "diqmt", "scope": "variable_region"}}
    path = write(tmp_path / "pairs.jsonl", [row("binder", binder_id=b, **chains) for b in ["a", "b"]])
    assert any(g["basis"] == "exact_vh_vl_pair" for g in process_batch([path])[3])


def cli(inputs, output):
    return subprocess.run([sys.executable, "-m", "cart_db.postprocess", *map(str, inputs),
                           "--output-dir", str(output)], capture_output=True, text=True)


def test_documented_cli_example_reproducibility_provenance_and_overwrite(tmp_path):
    repo = Path(os.environ["REVIEW_REPO"])
    inputs = [repo / "examples/post_extraction" / f"{n}.jsonl" for n in ["paper", "patent"]]
    before = [p.read_bytes() for p in inputs]
    out = tmp_path / "out"
    assert cli(inputs, out).returncode == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary == {"input_rows": 5, "output_rows": 4, "duplicate_serializations_removed": 1,
                       "review_events": 0, "candidate_groups": 1, "scientific_merges_applied": 0}
    rows = [json.loads(s) for s in (out / "normalized.jsonl").read_text().splitlines()]
    ev = [r["data"] for r in rows if r["table"] == "evidence"]
    paper = next(e for e in ev if e["source_type"] == "literature")
    assert paper["binder.kd"]["value"] == pytest.approx(2)
    assert paper["binder.kd"]["error"] == pytest.approx(.3)
    assert paper["binder.kd"]["raw"] == "0.002 ± 0.0003 µM"
    prov = [json.loads(s) for s in (out / "provenance.jsonl").read_text().splitlines()]
    for p in prov:
        assert p["original_row"] == json.loads(Path(p["input"]).read_text().splitlines()[p["line"] - 1])
    snapshot = {p.name: p.read_bytes() for p in out.iterdir()}
    assert cli(inputs, out).returncode != 0
    assert {p.name: p.read_bytes() for p in out.iterdir()} == snapshot
    again = tmp_path / "again"
    assert cli(inputs[::-1], again).returncode == 0
    assert {p.name: p.read_bytes() for p in again.iterdir()} == snapshot
    assert [p.read_bytes() for p in inputs] == before


def test_cli_validation_failure_leaves_no_output(tmp_path):
    path = write(tmp_path / "bad.jsonl", [row("binder", binder_id="b", unknown=1)])
    out = tmp_path / "out"
    assert cli([path], out).returncode != 0
    assert not out.exists()
