"""Database integration tests. CART_TEST_DSN must allow temporary database creation."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from cart_db import ingest, ingest_schema
from cart_db.identity import compare
from cart_db.schema_models import load_schema


# Create an isolated temporary database when CART_TEST_DSN is supplied, and remove it after the
# tests.
@pytest.fixture(scope="session")
def test_dsn():
    dsn = os.environ.get("CART_TEST_DSN")
    # When dsn is empty or false, record the skipped download and its cause in the snapshot.
    if not dsn:
        pytest.skip("Set CART_TEST_DSN to a disposable PostgreSQL server")
    name = "cart_ingest_test_" + uuid4().hex
    # Close the database connection when this operation finishes or raises.
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    params["dbname"] = name
    # Attempt this operation while preserving the explicit recovery/cleanup paths below.
    try:
        yield params
    # Drop the temporary integration database after the fixture succeeds or fails.
    finally:
        # Close the database connection when this operation finishes or raises.
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


# Connect to the isolated integration database and reset its current-schema contents for a test.
@pytest.fixture
def db(test_dsn):
    # Close the database connection when this operation finishes or raises.
    with psycopg.connect(**test_dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS cart CASCADE")
        ingest_schema.migrate(conn)
        yield conn


# Write a synthetic JSONL input without invoking an extraction agent.
def write(tmp_path, records, name="data.jsonl"):
    path = tmp_path / name
    # Build mapped values from records.
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    return path


# Build a minimal synthetic binder fixture with optional field overrides.
def binder(local_id="b", sequence="EVQLVGGGGSAVLTQ", **fields):
    return dict(table="binder", data=dict(binder_id=local_id, scfv_sequence=sequence, **fields))


# Build a source-observation fixture linked to the requested synthetic binder.
def evidence(local_id="e", owner="b", **fields):
    return dict(table="evidence", data={"record_id": local_id, "source_type": "literature",
                                       "source_id": "paper-1", "binder.binder_id": owner, **fields})


# Write and stage a synthetic input file, returning its database batch ID.
def stage(db, path):
    bid = ingest.stage_file(db, path)
    return bid, ingest.batch_status(db, bid)["records"]


# Read an accepted-table row count for integration assertions.
def count(db, table):
    return db.execute(sql.SQL("SELECT count(*) FROM cart.{}").format(sql.Identifier(table))).fetchone()[0]


# Verify that repeat import same sequence new names and distinct observations.
def test_repeat_import_same_sequence_new_names_and_distinct_observations(db, tmp_path):
    first = write(tmp_path, [binder(name="Clone A"), evidence()])
    bid, initial = stage(db, first)
    assert ingest.publish(db, bid)["counts"] == dict(published=2, pending=0, invalid=0)
    assert ingest.stage_file(db, first) == bid
    ingest.publish(db, bid)
    assert count(db, "evidence") == 1
    second = write(tmp_path, [binder(name="Clone-A"), evidence(source_id="paper-2")], "other.jsonl")
    bid2, _ = stage(db, second)
    result = ingest.publish(db, bid2)
    assert result["counts"]["published"] == 2
    assert count(db, "binder") == 1
    assert count(db, "evidence") == 2
    assert count(db, "entity_name") == 2
    # Collect distinct values from db.execute('SELECT binder_id FROM cart.evidence').
    ids = {str(r[0]) for r in db.execute("SELECT binder_id FROM cart.evidence")}
    assert len(ids) == 1
    original = db.execute("SELECT input_text FROM cart.import_batch WHERE batch_id=%s", (bid,)).fetchone()[0]
    assert original == first.read_text()
    assert initial[0]["local_id"] == "b"


# Verify that partial chain multiple matches saved independently.
def test_partial_chain_multiple_matches_saved_independently(db, tmp_path):
    heavy = dict(sequence="EVQLV", scope="variable_region")
    a = binder("a", heavy_chain=heavy, light_chain=dict(sequence="AVLTQ", scope="variable_region"))
    b = binder("b", "EVQLVGGGGSDIVMT", heavy_chain=heavy,
               light_chain=dict(sequence="DIVMT", scope="variable_region"))
    bid, records = stage(db, write(tmp_path, [a, b]))
    # Shared VH alone is insufficient to automatically dismiss either candidate.
    ingest.decide(db, records[0]["stage_id"], "new", "tester", "Source establishes construct A")
    ingest.decide(db, records[1]["stage_id"], "new", "tester", "Source establishes construct B")
    ingest.publish(db, bid)
    incoming = binder(sequence=None, heavy_chain=heavy)
    bid2, records = stage(db, write(tmp_path, [incoming, evidence()], "partial.jsonl"))
    matches = ingest.candidates(db, records[0]["stage_id"])
    assert len(matches) == 2
    # Build mapped values from matches.
    assert all(m["comparison"]["verdict"] == "possible" for m in matches)
    report = ingest.publish(db, bid2)
    assert report["counts"]["published"] == 2
    assert report["identity_counts"]["unresolved"] == 1
    assert count(db, "binder") == 3


# Verify that same input entities link without transitive grouping.
def test_same_input_entities_link_without_transitive_grouping(db, tmp_path):
    bid, _ = stage(db, write(tmp_path, [binder("a"), binder("b"), evidence(owner="b")]))
    assert ingest.publish(db, bid)["counts"]["published"] == 3
    assert count(db, "binder") == 1


# Verify that invalid measurement missing reference and bad json are preserved.
def test_invalid_measurement_missing_reference_and_bad_json_are_preserved(db, tmp_path):
    records = [binder(), evidence("bad", **{"binder.kd": dict(kind="single_value", value=True, unit="nM", raw="true")}),
               evidence("missing", owner="absent")]
    path = write(tmp_path, records)
    # Close the file reliably, including when reading or writing raises an error.
    with path.open("a") as out:
        out.write('{"table":"binder","data":{"binder_id":"bad", "name": NaN}}\n')
        out.write('{"table":"binder","table":"car","data":{}}\n')
    bid, _ = stage(db, path)
    result = ingest.publish(db, bid)
    assert result["counts"] == dict(published=1, pending=0, invalid=4)
    assert count(db, "evidence") == 0


# Verify that invalid parent blocks dependants and local ids override db ids.
def test_invalid_parent_blocks_dependants_and_local_ids_override_db_ids(db, tmp_path):
    bid, _ = stage(db, write(tmp_path, [binder()]))
    result = ingest.publish(db, bid)
    accepted_id = str(result["records"][0]["target_id"])
    broken = binder(accepted_id)
    broken["data"]["made_up_field"] = 1
    # Invalid row cannot mask an accepted ID of the same spelling.
    bid2, _ = stage(db, write(tmp_path, [broken, evidence(owner=accepted_id)], "bad.jsonl"))
    assert ingest.publish(db, bid2)["counts"]["published"] == 0


# Verify that measurement and module roundtrip.
def test_measurement_and_module_roundtrip(db, tmp_path):
    measurement = dict(kind="mean_with_standard_deviation", value=.002, error=.0003, unit="µM", raw="0.002 ± 0.0003 µM")
    modules = [dict(module_type="hinge", sequence="aepk"), dict(module_type="signaling_domain", sequence="rvkfs")]
    records = [binder(), dict(table="car", data=dict(car_id="c", modules=modules)),
               evidence(**{"binder.kd": measurement})]
    bid, _ = stage(db, write(tmp_path, records))
    ingest.publish(db, bid)
    exported = ingest.export_records(db)
    # Collect items from exported only where r['table'] == 'evidence'.
    ev = next(r["data"] for r in exported if r["table"] == "evidence")
    assert ev["binder.kd"]["value"] == pytest.approx(2)
    assert ev["binder.kd"]["error"] == pytest.approx(.3)
    assert ev["binder.kd"]["raw"] == measurement["raw"]
    # Collect items from exported only where r['table'] == 'car'.
    car = next(r["data"] for r in exported if r["table"] == "car")
    # Build mapped values from car['modules'].
    assert [m["module_type"] for m in car["modules"]] == ["hinge", "signaling_domain"]
    assert car["modules"][0]["sequence"] == "AEPK"


# Verify that car metadata conflict requires review.
def test_car_metadata_conflict_requires_review(db, tmp_path):
    # Build a synthetic CAR fixture for identity/reference checks.
    def car(label):
        return dict(table="car", data=dict(car_id="c", modules=[dict(module_type="hinge", sequence="AEPK", source_molecule=label)]))
    bid, _ = stage(db, write(tmp_path, [car("CD8")]))
    ingest.publish(db, bid)
    bid2, staged = stage(db, write(tmp_path, [car("CD28")], "second.jsonl"))
    assert ingest.publish(db, bid2)["counts"]["published"] == 1
    assert ingest.candidates(db, staged[0]["stage_id"])[0]["comparison"]["conflicts"]


# Verify that manufacturing missing parameters never auto match.
def test_manufacturing_missing_parameters_never_auto_match(db, tmp_path):
    process = dict(table="manufacturing", data=dict(manufacturing_id="m", vector_type="慢病毒", activation_method="CD3/CD28"))
    bid, records = stage(db, write(tmp_path, [process]))
    assert ingest.publish(db, bid)["counts"]["published"] == 1
    process["data"]["name"] = "Another reported name"
    bid2, records2 = stage(db, write(tmp_path, [process], "second.jsonl"))
    assert ingest.publish(db, bid2)["counts"]["published"] == 1
    match = ingest.candidates(db, records2[0]["stage_id"])[0]
    assert "culture_duration" in match["comparison"]["unknown"]


# Verify that combination reference mapping and conflicts.
def test_combination_reference_mapping_and_conflicts(db, tmp_path):
    records = [binder("b1"), binder("b2", "DIVMTGGGGSAEPK"),
               dict(table="car", data=dict(car_id="c", modules=[dict(module_type="hinge", sequence="AEPK")])),
               dict(table="manufacturing", data=dict(manufacturing_id="m", name="Protocol")),
               dict(table="abc_combination_db1", data=dict(combination_id="abc", binder_id="b1", car_id="c", manufacturing_id="m")),
               evidence("e1", owner="b1", combination_id="abc"), evidence("e2", owner="b2", combination_id="abc")]
    bid, staged = stage(db, write(tmp_path, records))
    ingest.decide(db, staged[3]["stage_id"], "new", "reviewer", "Protocol checked against source")
    result = ingest.publish(db, bid)
    assert result["counts"] == dict(published=6, pending=1, invalid=0)
    assert "disagree" in next(iter(result["pending_reasons"].values()))
    # Database also enforces consistency for writes bypassing the importer.
    wrong = db.execute("SELECT binder_id FROM cart.binder WHERE scfv_sequence='DIVMTGGGGSAEPK'").fetchone()[0]
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("UPDATE cart.evidence SET binder_id=%s", (wrong,))


# Verify that publication transaction rolls back on database failure.
def test_publication_transaction_rolls_back_on_database_failure(db, tmp_path):
    bid, _ = stage(db, write(tmp_path, [binder(), evidence()]))
    db.execute("ALTER TABLE cart.evidence ADD CONSTRAINT test_rejection CHECK (source_id <> 'paper-1')")
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(psycopg.errors.CheckViolation):
        ingest.publish(db, bid)
    assert count(db, "binder") == 0
    assert count(db, "publication_log") == 0
    assert ingest.batch_status(db, bid)["counts"]["pending"] == 2


# Verify that reviewed stage link cycles rejected.
def test_reviewed_stage_link_cycles_rejected(db, tmp_path):
    bid, records = stage(db, write(tmp_path, [binder("a", None), binder("b", None)]))
    # Build mapped values from records.
    a, b = [r["stage_id"] for r in records]
    ingest.decide(db, a, "link", "reviewer", "Source supported", target_stage_id=b)
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(ValueError, match="Cyclic"):
        ingest.decide(db, b, "link", "reviewer", "Source supported", target_stage_id=a)
    ingest.decide(db, b, "new", "reviewer", "New entity verified from source")
    assert ingest.publish(db, bid)["counts"]["published"] == 2
    assert count(db, "binder") == 1


# Verify that name selection never invents a name.
def test_name_selection_never_invents_a_name(db, tmp_path):
    bid, _ = stage(db, write(tmp_path, [binder(name="Clone A", aliases=["Clone-A"])]))
    result = ingest.publish(db, bid)
    target = result["records"][0]["target_id"]
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(ValueError, match="existing source-reported"):
        ingest.select_name(db, target, "Invented", "Jev/version", "Choice")
    ingest.select_name(db, target, "Clone-A", "reviewer", "Chosen display name")
    assert ingest.accepted(db, "binder", target)["name"] == "Clone-A"
    assert ingest.accepted(db, "binder", target)["aliases"] == ["Clone A"]
    assert count(db, "entity_name") == 2


# Verify that existing uuid references and context are preserved.
def test_existing_uuid_references_and_context_are_preserved(db, tmp_path):
    bid, _ = stage(db, write(tmp_path, [binder()]))
    target = ingest.publish(db, bid)["records"][0]["target_id"]
    context = tmp_path / "reasoning.md"
    context.write_text("Source-reviewed experimental conditions.")
    path = write(tmp_path, [evidence(owner=str(target))], "evidence-only.jsonl")
    bid2 = ingest.stage_file(db, path, [context])
    ingest.stage_file(db, path, [context])
    assert count(db, "import_context") == 1
    assert ingest.publish(db, bid2)["counts"]["published"] == 1


# Verify that forward references duplicate ids and schema drift.
def test_forward_references_duplicate_ids_and_schema_drift(db, tmp_path, monkeypatch):
    bid, _ = stage(db, write(tmp_path, [evidence(), binder()]))
    assert ingest.publish(db, bid)["counts"]["published"] == 2
    bid2, _ = stage(db, write(tmp_path, [binder(), binder(), evidence()], "duplicates.jsonl"))
    assert ingest.batch_status(db, bid2)["counts"]["invalid"] == 3
    # The callback returns 'changed'.
    monkeypatch.setattr(ingest_schema, "contract_hash", lambda: "changed")
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(ValueError, match="differs"):
        ingest.publish(db, bid2)


# Verify that reviewed observation link preserves both sources.
def test_reviewed_observation_link_preserves_both_sources(db, tmp_path):
    bid, _ = stage(db, write(tmp_path, [binder(), evidence()]))
    first = ingest.publish(db, bid)
    target = first["records"][1]["target_id"]
    bid2, pending = stage(db, write(tmp_path, [binder(name="Alias"), evidence(source_id="reprint")], "reprint.jsonl"))
    ingest.decide(db, pending[1]["stage_id"], "link", "reviewer", "Same original experiment reprinted", target_id=target)
    assert ingest.publish(db, bid2)["counts"]["published"] == 2
    assert count(db, "evidence") == 1
    assert db.execute("SELECT count(*) FROM cart.staged_record WHERE target_id=%s", (target,)).fetchone()[0] == 2


# Verify that migration is idempotent preserves legacy and detects drift.
def test_migration_is_idempotent_preserves_legacy_and_detects_drift(db, tmp_path, monkeypatch):
    db.execute("CREATE TABLE public.legacy_marker(value integer)")
    db.execute("INSERT INTO public.legacy_marker VALUES(1)")
    ingest_schema.migrate(db)
    assert db.execute("SELECT value FROM public.legacy_marker").fetchone()[0] == 1
    migration = next(ingest_schema.MIGRATIONS.glob("*.sql"))
    (tmp_path / migration.name).write_text(migration.read_text() + "\n-- changed\n")
    monkeypatch.setattr(ingest_schema, "MIGRATIONS", tmp_path)
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(ValueError, match="Applied migration changed"):
        ingest_schema.migrate(db)


# Verify that concurrent publications create one entity.
def test_concurrent_publications_create_one_entity(db, tmp_path, test_dsn):
    a, _ = stage(db, write(tmp_path, [binder(name="First")]))
    b, _ = stage(db, write(tmp_path, [binder(name="Second")], "second.jsonl"))

    # Run the test's importer or pipeline operation using isolated inputs and injected dependencies.
    def run(batch):
        # Close the database connection when this operation finishes or raises.
        with psycopg.connect(**test_dsn, autocommit=True) as other:
            return ingest.publish(other, batch)

    # Release this managed resource when the enclosed operation completes or fails.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (a, b)))
    # Build mapped values from results.
    assert all(r["counts"]["published"] == 1 for r in results)
    assert count(db, "binder") == 1


# Verify that schema fields all have storage columns.
def test_schema_fields_all_have_storage_columns(db):
    # Process each (table, fields) from load_schema().tables.items() independently.
    for table, fields in load_schema().tables.items():
        # Collect distinct values from the declared input collections.
        columns = {r[0] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='cart' AND table_name=%s", (table,))}
        # Collect distinct values from fields.
        assert {ingest_schema.column(f) for f in fields} <= columns


# Verify that image estimated ranges are supported and ordered.
def test_image_estimated_ranges_are_supported_and_ordered(db, tmp_path):
    records = [binder(), evidence(**{"binder.kd": dict(kind="image_estimated_range", lower=1, upper=3, unit="nM", raw="Figure estimate")})]
    bid, _ = stage(db, write(tmp_path, records))
    assert ingest.publish(db, bid)["counts"]["published"] == 2
    records[1]["data"]["binder.kd"]["upper"] = 1
    bid2, _ = stage(db, write(tmp_path, records, "bad-range.jsonl"))
    assert ingest.batch_status(db, bid2)["counts"]["invalid"] == 1


# Verify that manufacturing raw wording is not identity proof.
def test_manufacturing_raw_wording_is_not_identity_proof():
    a = dict(culture_duration=dict(kind="single_value", value=7, unit="day", raw="7 days"))
    b = dict(culture_duration=dict(kind="single_value", value=7, unit="day", raw="one week"))
    result = compare("manufacturing", a, b)
    assert result["verdict"] == "possible"
    assert "culture_duration" in result["differences"]


# Verify that new source sequence is available for future identity matching.
def test_new_source_sequence_is_available_for_future_identity_matching(db, tmp_path):
    bid, first = stage(db, write(tmp_path, [binder(sequence=None, name="Source-defined binder")]))
    ingest.decide(db, first[0]["stage_id"], "new", "reviewer", "Identity established from source despite missing sequence")
    target = ingest.publish(db, bid)["records"][0]["target_id"]
    bid2, second = stage(db, write(tmp_path, [binder(name="Later sequence")], "second.jsonl"))
    ingest.decide(db, second[0]["stage_id"], "link", "reviewer", "Source explicitly identifies this sequence", target_id=target)
    ingest.publish(db, bid2)
    bid3, _ = stage(db, write(tmp_path, [binder(name="Third source")], "third.jsonl"))
    result = ingest.publish(db, bid3)
    assert result["records"][0]["target_id"] == target
    assert count(db, "binder") == 1


# Verify that incomplete pending claim does not block complete identity.
def test_incomplete_pending_claim_does_not_block_complete_identity(db, tmp_path):
    heavy = dict(sequence="EVQLV", scope="variable_region")
    incomplete, _ = stage(db, write(tmp_path, [binder(sequence=None, heavy_chain=heavy)]))
    complete, _ = stage(db, write(tmp_path, [binder(heavy_chain=heavy)], "complete.jsonl"))
    assert ingest.publish(db, complete)["counts"]["published"] == 1
    assert ingest.publish(db, incomplete)["counts"]["published"] == 1


# Verify that conflicting accepted source claims are not hidden.
def test_conflicting_accepted_source_claims_are_not_hidden(db, tmp_path):
    bid, _ = stage(db, write(tmp_path, [binder()]))
    target = ingest.publish(db, bid)["records"][0]["target_id"]
    bid2, second = stage(db, write(tmp_path, [binder(sequence="DIVMTGGGGSAEPK")], "second.jsonl"))
    ingest.decide(db, second[0]["stage_id"], "link", "reviewer", "Source identity claim retained with conflicting sequence", target_id=target)
    ingest.publish(db, bid2)
    bid3, _ = stage(db, write(tmp_path, [binder(name="Third source")], "third.jsonl"))
    assert ingest.publish(db, bid3)["counts"]["published"] == 1
