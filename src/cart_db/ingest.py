"""Normalize JSONL into staging, resolve identities, and publish to PostgreSQL.

No model calls, destructive migration, or implicit overwrite of accepted data.
Run ``python -m cart_db.ingest --help`` for the command-line interface.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .agent_output import OutputError, _unique_object
from .config import settings
from .console import ChineseArgumentParser, TABLE_NAMES, json_text, report_text
from .identity import ENTITIES, compare, dump, features, strong_key
from .ingest_schema import LOCK, TABLES, check_contract, column, contract_hash, migrate, primary_key
from .postprocess import normalize_record
from .schema_models import load_schema


# Open an autocommit connection; each importer operation owns its explicit transaction.
def connect():
    return psycopg.connect(host=settings.pg_host, port=settings.pg_port,
                          dbname=settings.pg_database, user=settings.pg_user,
                          password=settings.pg_password, autocommit=True, connect_timeout=5)


# Execute a parameterized query and return dictionaries using database column names.
def rows(conn, query, params=()):
    # Close the query cursor after collecting its named result rows.
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


# Read one accepted record and restore dotted YAML field names from SQL column names.
def accepted(conn, table, record_id):
    query = sql.SQL("SELECT to_jsonb(t) - 'record_kind' AS data FROM cart.{} t WHERE {}=%s").format(
        sql.Identifier(table), sql.Identifier(primary_key(table)))
    found = rows(conn, query, (record_id,))
    # Stop with a diagnostic: No accepted {table} record: {record_id}.
    if not found:
        raise ValueError(f"No accepted {table} record: {record_id}")
    data = found[0]["data"]
    # Build mapped values from load_schema().tables[table].
    return {name: data[column(name)] for name in load_schema().tables[table]}


# Resolve an existing UUID only if it belongs to the requested scientific table.
def accepted_id(conn, table, value):
    # Attempt this operation while preserving the explicit recovery/cleanup paths below.
    try:
        value = UUID(str(value))
    # On (ValueError, TypeError), leave the result unresolved instead of inventing a value.
    except (ValueError, TypeError):
        return None
    found = conn.execute("SELECT record_id FROM cart.record WHERE record_id=%s AND table_name=%s",
                         (value, table)).fetchone()
    # Use found[0] when found is truthy; otherwise use None.
    return found[0] if found else None


# Read foreign-key destinations from the YAML contract instead of duplicating them in code.
def _references(table):
    # Collect items from load_schema().tables[table].items() only where spec.get('key') ==
    # 'foreign'.
    return [(name, spec["references"].split(".")[0])
            for name, spec in load_schema().tables[table].items() if spec.get("key") == "foreign"]


def stage_file(conn, path, contexts=(), on_status=None):
    """Record even rejected rows. Local IDs are scoped to this immutable batch."""
    path = Path(path)
    # Use a no-op callback when no progress listener was supplied.
    notify = on_status or (lambda message: None)
    notify("正在读取 JSONL，规范化序列和计量单位，并校验字段")
    content = path.read_bytes()
    input_text = content.decode("utf-8")
    checksum = hashlib.sha256(content).hexdigest()
    batch_id = uuid5(NAMESPACE_URL, "cart-import:" + checksum)
    staged = []
    # Keep line numbers as stable staging identities, including rows that fail QC.
    for line_no, line in enumerate(input_text.splitlines(), 1):
        # Ignore blank lines without renumbering the remaining source records.
        if not line.strip():
            continue
        row = dict(stage_id=uuid5(batch_id, str(line_no)), line_number=line_no,
                   table_name=None, local_id=None, original=None, normalized=None, audit=[], errors=[])
        # Capture malformed rows as QC errors so the batch retains its original input.
        try:
            # Reject NaN and infinity spellings that are not valid finite scientific JSON numbers.
            def invalid_constant(value):
                raise OutputError(f"Non-finite JSON number: {value}")

            # Reject numeric overflow during JSON decoding before it reaches normalization or
            # storage.
            def finite_float(value):
                number = float(value)
                # Reject overflow such as 1e999 before it becomes a non-finite Python float.
                if not math.isfinite(number):
                    invalid_constant(value)
                return number

            item = json.loads(line, object_pairs_hook=_unique_object,
                              parse_constant=invalid_constant, parse_float=finite_float)
            row["original"] = item
            # Require the same table/data envelope as the extractor.
            if not isinstance(item, dict) or set(item) != {"table", "data"}:
                raise OutputError("Expected exactly table and data")
            table = item["table"]
            # Reject unsupported table names before inspecting their schema.
            if not isinstance(table, str) or table not in TABLES:
                raise OutputError("Unknown table")
            row["table_name"] = table
            # Reserve even a rejected row's declared label. It must not silently
            # fall through to an accepted UUID of the same spelling.
            if isinstance(item["data"], dict):
                local_id = item["data"].get(primary_key(table))
                # Reserve a source label even when the rest of its record may later fail QC.
                if isinstance(local_id, str):
                    row["local_id"] = local_id
            data, audit = normalize_record(table, item["data"])
            row.update(local_id=data[primary_key(table)], normalized=data, audit=audit)
            # Evidence validation checks direct owners before database reference resolution.
            if table == "evidence":
                # Collect items from load_schema().entities only where data[e.fk_column] is not
                # None.
                owners = [e for e in load_schema().entities if data[e.fk_column] is not None]
                # An observation without an entity owner cannot be admitted.
                if not owners:
                    raise OutputError("Evidence must reference at least one entity")
                # Validate each kind of evidence measurement against its declared owner.
                for entity in load_schema().entities:
                    # Do not attach entity-specific measurements to an absent reference.
                    if entity not in owners and any(v is not None for k, v in data.items()
                                                    if k.startswith(entity.kind + ".")):
                        raise OutputError(f"{entity.kind} fields without an entity reference")
        # Retain the validation error on this staged row so one invalid row does not discard its
        # neighbors.
        except (ValueError, TypeError, KeyError) as exc:
            row["errors"].append(str(exc))
        staged.append(row)

    # Read contexts before opening the transaction, so missing files cannot leave a partial batch.
    context_data = [(Path(p).name, Path(p).read_text(encoding="utf-8")) for p in contexts]
    # Persist a complete staging batch and its context under one transaction lock.
    with conn.transaction():
        notify("正在核对记录引用，并保存原始记录、规范化结果和质检问题")
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        check_contract(conn)
        existing = conn.execute("SELECT batch_id,schema_hash FROM cart.import_batch WHERE checksum=%s",
                                (checksum,)).fetchone()
        by_local = {}
        # Build a table-scoped index of all declared local labels.
        for row in staged:
            # Only declared labels participate in duplicate and dependency checks.
            if row["local_id"] is not None:
                by_local.setdefault((row["table_name"], row["local_id"]), []).append(row)
        # Inspect every local-label group, including otherwise identical repetitions.
        for duplicates in by_local.values():
            # Duplicate labels are rejected rather than arbitrarily selecting a row.
            if len(duplicates) > 1:
                # Mark every occurrence invalid so no dependent row can resolve ambiguously.
                for row in duplicates:
                    row["errors"].append("Duplicate local ID within input table")
        # Propagate invalid dependencies until all dependants have been marked.
        changed = True
        # Repeat until invalidity has propagated through every dependent record.
        while changed:
            changed = False
            # Revisit remaining valid rows as earlier dependency failures propagate.
            for row in staged:
                # Already-invalid rows need no further dependency checks.
                if row["errors"]:
                    continue
                # Resolve each outgoing reference against local rows first, then accepted UUIDs.
                for field, target in _references(row["table_name"]):
                    value = row["normalized"][field]
                    # Leave optional absent references unknown.
                    if value is None:
                        continue
                    local = by_local.get((target, value))
                    # A bad local target or missing accepted target invalidates the dependent row.
                    if ((local and any(r["errors"] for r in local))
                            or (not local and not accepted_id(conn, target, value))):
                        row["errors"].append(f"Unresolved or invalid reference {field}: {value}")
                        changed = True
                        break
        # A new file checksum creates a new immutable batch.
        if not existing:
            conn.execute("""INSERT INTO cart.import_batch
                (batch_id,checksum,input_name,input_text,schema_hash) VALUES (%s,%s,%s,%s,%s)""",
                         (batch_id, checksum, str(path.resolve()), input_text, contract_hash()))
            # Save both rejected and valid source assertions for later inspection.
            for row in staged:
                # Use Jsonb(row['original']) when row original is supplied; otherwise use None.
                conn.execute("""INSERT INTO cart.staged_record
                    (stage_id,batch_id,line_number,table_name,local_id,original,normalized,audit,errors,status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (row["stage_id"], batch_id, row["line_number"], row["table_name"], row["local_id"],
                     Jsonb(row["original"]) if row["original"] is not None else None,
                     Jsonb(row["normalized"]) if row["normalized"] is not None else None,
                     Jsonb(row["audit"]), Jsonb(row["errors"]), "invalid" if row["errors"] else "pending"))
                # Only QC-valid scientific entities receive identity lookup features.
                if not row["errors"] and row["table_name"] in ENTITIES:
                    # Store each comparison basis separately rather than relying on one global
                    # fingerprint.
                    for basis, fingerprint, value in features(row["table_name"], row["normalized"]):
                        conn.execute("""INSERT INTO cart.identity_feature(stage_id,basis,fingerprint,value)
                            VALUES (%s,%s,%s,%s)""", (row["stage_id"], basis, fingerprint, Jsonb(value)))
        # Revalidate unpublished rows when the active contract changes; retain prior validation in
        # the audit.
        elif existing[1] != contract_hash():
            # Build mapped values from rows(conn, 'SELECT * FROM cart.staged_record WHERE
            # batch_id=%s', (batch_id,)).
            previous = {str(r["stage_id"]): r for r in rows(conn,
                "SELECT * FROM cart.staged_record WHERE batch_id=%s", (batch_id,))}
            # Refresh each staged row against the new contract.
            for row in staged:
                old = previous[str(row["stage_id"])]
                # Published assertions are historical records and must not be reinterpreted in
                # place.
                if old["status"] == "published":
                    continue
                audit = [dict(reason="previous_schema_validation", before={
                    "schema_hash": existing[1], "normalized": old["normalized"],
                    "audit": old["audit"], "errors": old["errors"]}, after=None), *row["audit"]]
                # Use 'invalid' when row['errors']; otherwise use 'pending'.
                conn.execute("""UPDATE cart.staged_record SET normalized=%s,audit=%s,errors=%s,status=%s
                    WHERE stage_id=%s""", (Jsonb(row["normalized"]), Jsonb(audit), Jsonb(row["errors"]),
                        "invalid" if row["errors"] else "pending", row["stage_id"]))
                conn.execute("DELETE FROM cart.identity_feature WHERE stage_id=%s", (row["stage_id"],))
                # Rebuild lookup features only for valid entity rows after revalidation.
                if not row["errors"] and row["table_name"] in ENTITIES:
                    # Replace stale candidate indexes with features from the newly normalized data.
                    for basis, fingerprint, value in features(row["table_name"], row["normalized"]):
                        conn.execute("INSERT INTO cart.identity_feature(stage_id,basis,fingerprint,value) VALUES (%s,%s,%s,%s)",
                                     (row["stage_id"], basis, fingerprint, Jsonb(value)))
            conn.execute("UPDATE cart.import_batch SET schema_hash=%s WHERE batch_id=%s", (contract_hash(), batch_id))
        # Retain every supplied context attachment with its own checksum.
        for name, text in context_data:
            conn.execute("""INSERT INTO cart.import_context(batch_id,name,checksum,content)
                VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                         (batch_id, name, hashlib.sha256(text.encode()).hexdigest(), text))
    return batch_id


# Fetch the original/normalized assertion and its current publication state by staging UUID.
def get_stage(conn, stage_id):
    found = rows(conn, "SELECT * FROM cart.staged_record WHERE stage_id=%s", (stage_id,))
    # Stop with a diagnostic: Unknown staging record: {stage_id}.
    if not found:
        raise ValueError(f"Unknown staging record: {stage_id}")
    return found[0]


def candidates(conn, stage_id):
    """Return candidate claims and accepted entities, without transitive grouping."""
    row = get_stage(conn, stage_id)
    # Observations and invalid rows do not enter entity candidate matching.
    if row["table_name"] not in ENTITIES or row["status"] == "invalid":
        return []
    found = rows(conn, """SELECT DISTINCT other.* FROM cart.identity_feature incoming
        JOIN cart.identity_feature candidate
          ON incoming.basis=candidate.basis AND incoming.fingerprint=candidate.fingerprint
        JOIN cart.staged_record other ON other.stage_id=candidate.stage_id
        WHERE incoming.stage_id=%s AND other.stage_id<>%s
          AND other.table_name=%s AND other.status<>'invalid'""",
                 (stage_id, stage_id, row["table_name"]))
    if row["table_name"] == "binder":
        # Partial-chain containment is only a retrieval hint, never an identity rule.
        found.extend(rows(conn, """SELECT DISTINCT other.* FROM cart.identity_feature incoming
            JOIN cart.identity_feature candidate
              ON (incoming.basis=candidate.basis
                OR (incoming.basis IN ('heavy_chain','light_chain') AND candidate.basis='scfv')
                OR (incoming.basis='scfv' AND candidate.basis IN ('heavy_chain','light_chain')))
            JOIN cart.staged_record other ON other.stage_id=candidate.stage_id
            WHERE incoming.stage_id=%s AND incoming.basis IN ('heavy_chain','light_chain','scfv')
              AND other.stage_id<>%s AND other.table_name='binder' AND other.status<>'invalid'
              AND (strpos(incoming.value #>> '{}',candidate.value #>> '{}')>0
                OR strpos(candidate.value #>> '{}',incoming.value #>> '{}')>0)""", (stage_id, stage_id)))
    result = {}
    # Collapse retrieved assertions by their accepted target or staging identity.
    for other in found:
        target = other["target_id"]
        # Use ('accepted', str(target)) when target is truthy; otherwise use ('staging',
        # str(other['stage_id'])).
        key = ("accepted", str(target)) if target else ("staging", str(other["stage_id"]))
        # Several source assertions can retrieve the same candidate; compare that target once.
        if key in result:
            continue
        # Use accepted(conn, row['table_name'], target) when target is truthy; otherwise use
        # other['normalized'].
        data = accepted(conn, row["table_name"], target) if target else other["normalized"]
        # Choose the result according to target is truthy; preserve the alternate path for the other
        # case.
        claims = rows(conn, "SELECT stage_id,normalized FROM cart.staged_record WHERE target_id=%s ORDER BY stage_id",
                      (target,)) if target else [other]
        comparisons = [compare(row["table_name"], row["normalized"], data)]
        # Compare every linked source assertion so conflicts hidden by the accepted snapshot remain
        # visible.
        if target:
            # Build mapped values from claims.
            comparisons.extend(compare(row["table_name"], row["normalized"], claim["normalized"])
                               for claim in claims)
        # Collect distinct values from comparisons.
        verdicts = {c["verdict"] for c in comparisons}
        # Collect distinct values from comparisons; c.get('conflicts', []).
        conflicts = sorted({field for c in comparisons for field in c.get("conflicts", [])})
        # Explicit contradictions take precedence over any positive source comparison.
        if "conflict" in verdicts or {"same", "distinct"} <= verdicts:
            comparison = dict(verdict="conflict", conflicts=conflicts,
                              reason="来源记录之间存在明确的身份冲突，禁止自动合并。")
        # Annotation differences prevent automatic identity even without a hard conflict verdict.
        elif conflicts:
            comparison = dict(verdict="possible", conflicts=conflicts,
                              reason="来源注释存在差异，需要核查。")
        # Use an exact match only after checking all linked claims for contradictions.
        elif "same" in verdicts:
            # Collect items from comparisons only where c['verdict'] == 'same'.
            comparison = next(c for c in comparisons if c["verdict"] == "same")
        # Process similarity is reported separately from exact identity.
        elif "similar" in verdicts:
            # Collect items from comparisons only where c['verdict'] == 'similar'.
            comparison = next(c for c in comparisons if c["verdict"] == "similar")
        # Only unanimous distinct comparisons establish this aggregate distinct verdict.
        elif verdicts == {"distinct"}:
            comparison = comparisons[0]
        # Retain a possible verdict when the claims do not unanimously establish one stronger
        # outcome.
        else:
            # Collect items from comparisons only where c['verdict'] == 'possible'.
            comparison = next(c for c in comparisons if c["verdict"] == "possible")
        # Build mapped values from claims.
        result[key] = dict(location=key[0], id=key[1], table=row["table_name"], data=data,
                           supporting_stage_ids=[str(claim["stage_id"]) for claim in claims],
                           comparison=comparison)
    # The callback returns (r['location'], r['id']).
    return sorted(result.values(), key=lambda r: (r["location"], r["id"]))


def decide(conn, stage_id, action, reviewer, reason, target_id=None, target_stage_id=None):
    """Persist a reviewer decision. It takes effect only during publication."""
    # Stop with a diagnostic: Reviewer and source-based reason are required.
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Reviewer and source-based reason are required")
    # Stop with a diagnostic: new needs no target; link needs exactly one target.
    if action not in ("new", "link") or ((target_id is not None) + (target_stage_id is not None)) != (action == "link"):
        raise ValueError("new needs no target; link needs exactly one target")
    # Lock decision validation and insertion together so targets cannot change between them.
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        check_contract(conn)
        row = get_stage(conn, stage_id)
        # Stop with a diagnostic: Only pending records can receive identity decisions.
        if row["status"] != "pending":
            raise ValueError("Only pending records can receive identity decisions")
        # Stop with a diagnostic: Target must be an accepted record of the same table.
        if target_id and not accepted_id(conn, row["table_name"], target_id):
            raise ValueError("Target must be an accepted record of the same table")
        # A staging target needs same-table validity and cycle checks before linking.
        if target_stage_id:
            other = get_stage(conn, target_stage_id)
            # Stop with a diagnostic: Target staging record must be valid and of the same table.
            if other["table_name"] != row["table_name"] or other["status"] == "invalid":
                raise ValueError("Target staging record must be valid and of the same table")
            seen = {str(stage_id)}
            current = str(target_stage_id)
            # Follow the most recent staging links to detect indirect cycles.
            while current:
                # A repeated staging UUID would create a circular identity decision.
                if current in seen:
                    raise ValueError("Cyclic staging identity decisions")
                seen.add(current)
                previous = conn.execute("""SELECT target_stage_id FROM cart.identity_decision
                    WHERE stage_id=%s ORDER BY decision_id DESC LIMIT 1""", (current,)).fetchone()
                # Use str(previous[0]) when previous and previous[0]; otherwise use None.
                current = str(previous[0]) if previous and previous[0] else None
        conn.execute("""INSERT INTO cart.identity_decision
            (stage_id,action,target_id,target_stage_id,reviewer,reason) VALUES (%s,%s,%s,%s,%s,%s)""",
                     (stage_id, action, target_id, target_stage_id, reviewer, reason))


# Insert the typed UUID registry entry and scientific row inside the caller's transaction.
def _insert_record(conn, table, data):
    fields = load_schema().tables[table]
    record_id = data[primary_key(table)]
    conn.execute("INSERT INTO cart.record(record_id,table_name) VALUES (%s,%s)", (record_id, table))
    # Build mapped values from fields.items().
    values = [Jsonb(data[name]) if data[name] is not None and spec["type"] in ("json", "measurement")
              else data[name] for name, spec in fields.items()]
    # Build mapped values from fields.
    conn.execute(sql.SQL("INSERT INTO cart.{} ({}) VALUES ({})").format(
        sql.Identifier(table), sql.SQL(",").join(sql.Identifier(column(name)) for name in fields),
        sql.SQL(",").join(sql.Placeholder() for _ in fields)), values)
    return record_id


# Record the publication mapping, identity audit, and source names without overwriting source
# assertions.
def _finish(conn, row, target, method, details):
    details = {"comparison_policy": "source-admission-v3", **details}
    # Use details.get('identity_status', 'resolved') when row table_name is in ENTITIES; otherwise
    # use None.
    conn.execute("""UPDATE cart.staged_record SET status='published',target_id=%s,published_at=now(),
        identity_status=%s,identity_details=%s WHERE stage_id=%s""",
        (target, details.get("identity_status", "resolved") if row["table_name"] in ENTITIES else None,
         Jsonb(details) if row["table_name"] in ENTITIES else None, row["stage_id"]))
    conn.execute("INSERT INTO cart.publication_log(stage_id,target_id,method,details) VALUES (%s,%s,%s,%s)",
                 (row["stage_id"], target, method, Jsonb(details)))
    # Collect names only for scientific entities, not combinations or observations.
    if row["table_name"] in ENTITIES:
        data = row["normalized"]
        # Preserve each source-reported name and alias as an auditable assertion.
        for name in [data.get("name"), *(data.get("aliases") or [])]:
            # Skip unusable labels rather than registering blank display names.
            if isinstance(name, str) and name.strip():
                conn.execute("""INSERT INTO cart.entity_name(entity_id,name,stage_id)
                    VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""", (target, name, row["stage_id"]))


# Replace local references with accepted UUIDs; return None while any dependency is unresolved.
def _mapped_data(conn, row):
    # New optional fields remain unknown for staging records saved before migration.
    data = {field: deepcopy(row["normalized"].get(field))
            for field in load_schema().tables[row["table_name"]]}
    # Rewrite every declared foreign key using the batch's resolved targets.
    for field, table in _references(row["table_name"]):
        value = data[field]
        # An absent optional reference stays absent.
        if value is None:
            continue
        local = rows(conn, """SELECT status,target_id FROM cart.staged_record
            WHERE batch_id=%s AND table_name=%s AND local_id=%s""", (row["batch_id"], table, value))
        # A local declaration takes precedence over a same-spelled accepted UUID.
        if local:
            # Defer publication until exactly one local target has been published.
            if len(local) != 1 or local[0]["status"] != "published":
                return None
            target = local[0]["target_id"]
        # With no batch-local target, accept only an existing UUID in the expected scientific table.
        else:
            target = accepted_id(conn, table, value)
        # An unresolved target defers the entire dependent record.
        if not target:
            return None
        data[field] = str(target)
    return data


def publish(conn, batch_id, on_status=None):
    """Re-query under a short lock, then atomically publish all resolvable records.

    Nothing is overwritten. Repeated source observations in different batches are
    retained unless a reviewer explicitly links their evidence records.
    """
    pending_reasons = {}
    # Use a no-op callback when no progress listener was supplied.
    notify = on_status or (lambda message: None)
    notify("正在比对实体，确定复用或新增，并重写组合和证据引用")
    # Serialize identity resolution and publication in one transaction to avoid concurrent
    # duplicates.
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        check_contract(conn)
        progress = True
        # Retry deferred rows while publishing dependencies makes further progress possible.
        while progress:
            progress = False
            pending = rows(conn, """SELECT * FROM cart.staged_record WHERE batch_id=%s AND status='pending'
                ORDER BY CASE table_name WHEN 'binder' THEN 1 WHEN 'car' THEN 2
                  WHEN 'manufacturing' THEN 3 WHEN 'abc_combination_db1' THEN 4 ELSE 5 END,line_number""",
                           (batch_id,))
            # Process entities before combinations and observations, respecting source line order.
            for row in pending:
                stage_id, table = row["stage_id"], row["table_name"]
                key = str(stage_id)
                decisions = rows(conn, """SELECT * FROM cart.identity_decision WHERE stage_id=%s
                    ORDER BY decision_id DESC LIMIT 1""", (stage_id,))
                # Use decisions[0] when decisions is truthy; otherwise use None.
                decision = decisions[0] if decisions else None
                target, method, details = None, "", {}
                # Apply the latest explicit reviewer decision before automatic identity rules.
                if decision:
                    details = dict(decision_id=decision["decision_id"], reviewer=decision["reviewer"],
                                   reason=decision["reason"])
                    method = "reviewed_" + decision["action"]
                    # A reviewed link reuses its target rather than inserting a new identity.
                    if decision["action"] == "link":
                        target = decision["target_id"]
                        # Resolve a reviewed staging target through its publication mapping.
                        if decision["target_stage_id"]:
                            target = get_stage(conn, decision["target_stage_id"])["target_id"]
                        # Defer links whose reviewed target has not yet been published.
                        if not target:
                            pending_reasons[key] = "Reviewed target is still pending"
                            continue
                        # Even reviewed observation links must retain the same mapped owners.
                        if table not in ENTITIES:
                            mapped = _mapped_data(conn, row)
                            # Even reviewed observation links must wait for all owners to resolve.
                            if mapped is None:
                                pending_reasons[key] = "Dependent entity or combination is pending"
                                continue
                            existing = accepted(conn, table, target)
                            # A reviewed link cannot attach an observation to different resolved
                            # owners.
                            if any(mapped[f] != existing[f] for f, _ in _references(table)):
                                raise ValueError("Reviewed link has conflicting resolved references")
                # For new entity candidates, assess exact matches, conflicts, uncertainty, and
                # normalization flags.
                if table in ENTITIES and target is None:
                    matches = candidates(conn, stage_id)
                    # Collect items from matches only where m['location'] == 'accepted' and
                    # m['comparison']['verdict'] == 'same'.
                    same = [m for m in matches if m["location"] == "accepted" and m["comparison"]["verdict"] == "same"]
                    # Collect items from matches only where m['comparison']['verdict'] ==
                    # 'conflict'.
                    conflicts = [m for m in matches if m["comparison"]["verdict"] == "conflict"]
                    # Collect matching items from matches using the explicit completeness/type
                    # filters below.
                    possible = [m for m in matches if m["comparison"]["verdict"] == "possible"
                                and (m["location"] == "accepted" or strong_key(table, m["data"])
                                     or m["comparison"].get("conflicts"))]
                    # Collect items from matches only where m['comparison']['verdict'] == 'similar'.
                    similar = [m for m in matches if m["comparison"]["verdict"] == "similar"]
                    # Collect items from row['audit'] only where e['reason'].startswith('review_').
                    flags = [e for e in row["audit"] if e["reason"].startswith("review_")]
                    # A new exact accepted match makes a prior reviewed-new decision stale.
                    if decision and same:
                        pending_reasons[key] = "Reviewed new entity now has an exact accepted match; review again"
                        continue
                    # Automatic identity selection applies only in the absence of a reviewer
                    # decision.
                    if not decision:
                        # Automatic reuse requires exactly one accepted match and no effective
                        # ambiguity or review flags.
                        if len(same) == 1 and not conflicts and not possible and not flags:
                            target, method = same[0]["id"], "exact_identity"
                            details = same[0]["comparison"]
                        # Admit a separate entity and record conflict, ambiguity, similarity, or
                        # resolution for later review.
                        else:
                            # Choose the result according to conflicts is truthy; preserve the
                            # alternate path for the other case.
                            identity_status = ("conflict" if conflicts else "unresolved" if
                                possible or len(same) > 1 or flags else "similar" if similar else
                                "resolved")
                            # Use 'new_complete_identity' when identity_status == 'resolved' and
                            # strong_key(table, row['normalized']); otherwise use
                            # 'new_source_entity'.
                            method = "new_complete_identity" if identity_status == "resolved" and strong_key(table, row["normalized"]) else "new_source_entity"
                            # Collect items from matches only where m['comparison']['verdict'] !=
                            # 'distinct'.
                            details = dict(identity_status=identity_status,
                                reason="保存来源实体；身份是否重复与数据入库分别处理。",
                                candidates=[{k: m[k] for k in ("location", "id", "comparison", "supporting_stage_ids")}
                                            for m in matches if m["comparison"]["verdict"] != "distinct"],
                                normalization_flags=flags)
                # Create or resolve a row only after reference mapping succeeds.
                if target is None:
                    data = _mapped_data(conn, row)
                    # Dependent rows remain pending without inventing foreign keys.
                    if data is None:
                        pending_reasons[key] = "Dependent entity or combination is pending"
                        continue
                    # Reuse a combination only when its resolved A/B/C tuple matches.
                    if table == "abc_combination_db1":
                        existing = conn.execute("""SELECT combination_id FROM cart.abc_combination_db1
                            WHERE binder_id=%s AND car_id=%s AND manufacturing_id=%s""",
                            (data["binder_id"], data["car_id"], data["manufacturing_id"])).fetchone()
                        # An existing A/B/C tuple supplies the accepted combination ID.
                        if existing:
                            target, method = existing[0], "existing_abc_combination"
                    # Evidence linked to a combination must agree with its entity owners.
                    if table == "evidence" and data["combination_id"]:
                        combo = accepted(conn, "abc_combination_db1", data["combination_id"])
                        # Keep contradictory evidence pending rather than rewriting its reported
                        # ownership.
                        if any(data[e.fk_column] is not None and data[e.fk_column] != combo[e.id_column]
                               for e in load_schema().entities):
                            pending_reasons[key] = "Resolved evidence references disagree with its ABC combination"
                            continue
                    # Insert a new accepted record only when neither reviewed linking nor automatic
                    # reuse supplied a target.
                    if target is None:
                        data[primary_key(table)] = str(uuid4())
                        target = _insert_record(conn, table, data)
                        # Use the specific publication method when set; otherwise label a newly
                        # admitted observation/combination.
                        method = method or "new_source_observation_or_combination"
                _finish(conn, row, target, method, details)
                pending_reasons.pop(key, None)
                progress = True
        notify("正在检查数据库约束并提交本批次可确定的记录")
    result = batch_status(conn, batch_id)
    result["pending_reasons"] = pending_reasons
    return result


# Report publication counts separately from identity-review counts, retaining per-row diagnostics.
def batch_status(conn, batch_id):
    # Stop with a diagnostic: Unknown import batch.
    if not conn.execute("SELECT 1 FROM cart.import_batch WHERE batch_id=%s", (batch_id,)).fetchone():
        raise ValueError("Unknown import batch")
    records = rows(conn, """SELECT stage_id,line_number,table_name,local_id,status,target_id,errors,audit,identity_status,identity_details
        FROM cart.staged_record WHERE batch_id=%s ORDER BY line_number""", (batch_id,))
    # Build mapped values from ('published', 'pending', 'invalid').
    counts = {status: sum(r["status"] == status for r in records) for status in ("published", "pending", "invalid")}
    # Build mapped values from ('resolved', 'unresolved', 'similar', 'conflict').
    identity_counts = {state: sum(r["identity_status"] == state for r in records)
                       for state in ("resolved", "unresolved", "similar", "conflict")}
    return dict(batch_id=str(batch_id), counts=counts, identity_counts=identity_counts, records=records)


def select_name(conn, entity_id, name, selector, reason):
    """Accept a human/Jev selection from collected names; do not call a model."""
    # Stop with a diagnostic: Selector (including model/version) and reason are required.
    if not selector.strip() or not reason.strip():
        raise ValueError("Selector (including model/version) and reason are required")
    # Record display-name selection and its audit atomically.
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        check_contract(conn)
        record = conn.execute("SELECT table_name FROM cart.record WHERE record_id=%s", (entity_id,)).fetchone()
        # Stop with a diagnostic: Name selection requires an accepted entity.
        if not record or record[0] not in ENTITIES:
            raise ValueError("Name selection requires an accepted entity")
        # Stop with a diagnostic: Selected name must be an existing source-reported name.
        if not conn.execute("SELECT 1 FROM cart.entity_name WHERE entity_id=%s AND name=%s", (entity_id, name)).fetchone():
            raise ValueError("Selected name must be an existing source-reported name")
        conn.execute(sql.SQL("UPDATE cart.{} SET name=%s WHERE {}=%s").format(
            sql.Identifier(record[0]), sql.Identifier(primary_key(record[0]))), (name, entity_id))
        # Only binders have a YAML aliases field; other entity names remain in the shared name
        # table.
        if record[0] == "binder":
            # Build mapped values from the declared input collections.
            aliases = [r[0] for r in conn.execute("""SELECT DISTINCT name FROM cart.entity_name
                WHERE entity_id=%s AND name<>%s ORDER BY name""", (entity_id, name))]
            conn.execute("UPDATE cart.binder SET aliases=%s WHERE binder_id=%s", (Jsonb(aliases), entity_id))
        conn.execute("INSERT INTO cart.name_selection(entity_id,name,selector,reason) VALUES (%s,%s,%s,%s)",
                     (entity_id, name, selector, reason))


def export_records(conn):
    """Accepted five-table JSONL; source assertions remain separately in staging."""
    # Export all tables from a single consistent read-only snapshot.
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        check_contract(conn)
        result = []
        # Export tables in dependency order for a usable five-table interchange file.
        for table in TABLES:
            # Read each accepted UUID using the active YAML field mapping.
            for (record_id,) in conn.execute("SELECT record_id FROM cart.record WHERE table_name=%s ORDER BY record_id", (table,)):
                result.append(dict(table=table, data=accepted(conn, table, record_id)))
        return result


# Dispatch migration/import/review/export commands and translate errors for command-line operators.
def main(argv=None):
    parser = ChineseArgumentParser(description="JSONL 规范化、质检、实体比对与 PostgreSQL 入库")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON，保留字段和状态代码")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="在 cart 中执行增量数据库迁移")
    stage = commands.add_parser("stage", help="规范化、质检并暂存一个 JSONL 文件")
    stage.add_argument("path", type=Path)
    stage.add_argument("--context", type=Path, action="append", default=[], help="保存来源依据、异常和追溯文件")
    # Both batch inspection and publication require a batch identifier.
    for command in ("status", "publish"):
        commands.add_parser(command).add_argument("batch_id", type=UUID)
    commands.add_parser("candidates").add_argument("stage_id", type=UUID)
    commands.add_parser("inspect", help="查看规范化记录、质检结果和来源资料").add_argument("stage_id", type=UUID)
    decision = commands.add_parser("decide")
    decision.add_argument("stage_id", type=UUID)
    decision.add_argument("action", choices=("new", "link"))
    targets = decision.add_mutually_exclusive_group()
    targets.add_argument("--target-id", type=UUID)
    targets.add_argument("--target-stage-id", type=UUID)
    decision.add_argument("--reviewer", required=True)
    decision.add_argument("--reason", required=True)
    naming = commands.add_parser("select-name")
    naming.add_argument("entity_id", type=UUID)
    naming.add_argument("name")
    naming.add_argument("--selector", required=True)
    naming.add_argument("--reason", required=True)
    commands.add_parser("export", help="导出已入库的 JSONL 到标准输出")
    args = parser.parse_args(argv)
    # Attempt this operation while preserving the explicit recovery/cleanup paths below.
    try:
        # Close the database connection when this operation finishes or raises.
        with connect() as conn:
            # Dispatch the migrate command through its dedicated importer operation.
            if args.command == "migrate":
                migrate(conn)
                result = {"migrations": "applied"}
            # Dispatch the stage command through its dedicated importer operation.
            elif args.command == "stage":
                result = batch_status(conn, stage_file(conn, args.path, args.context))
            # Dispatch the status command through its dedicated importer operation.
            elif args.command == "status":
                result = batch_status(conn, args.batch_id)
            # Dispatch the publish command through its dedicated importer operation.
            elif args.command == "publish":
                result = publish(conn, args.batch_id)
            # Dispatch the candidates command through its dedicated importer operation.
            elif args.command == "candidates":
                result = candidates(conn, args.stage_id)
            # Dispatch the inspect command through its dedicated importer operation.
            elif args.command == "inspect":
                result = get_stage(conn, args.stage_id)
                result["context"] = rows(conn, "SELECT name,content FROM cart.import_context WHERE batch_id=%s ORDER BY name,checksum",
                                         (result["batch_id"],))
            # Dispatch the decide command through its dedicated importer operation.
            elif args.command == "decide":
                decide(conn, args.stage_id, args.action, args.reviewer, args.reason, args.target_id, args.target_stage_id)
                result = {"decision": "recorded"}
            # Dispatch the select-name command through its dedicated importer operation.
            elif args.command == "select-name":
                select_name(conn, args.entity_id, args.name, args.selector, args.reason)
                result = {"name_selection": "recorded"}
            # The remaining command exports accepted records as JSONL without staging/audit
            # metadata.
            else:
                # Write one accepted scientific record per line; source assertions stay in staging.
                for record in export_records(conn):
                    print(dump(record))
                return 0
        # Machine output preserves field/status codes for scripting.
        if args.json:
            print(json_text(result))
        # Render batch operations using the shared operator-facing report.
        elif args.command in ("stage", "status", "publish"):
            print(report_text(result))
        # Dispatch the migrate command through its dedicated importer operation.
        elif args.command == "migrate":
            print("数据库迁移及字段版本核对完成")
        # Dispatch the decide command through its dedicated importer operation.
        elif args.command == "decide":
            print("审核决定已保存；请再次运行 publish 完成入库")
        # Dispatch the select-name command through its dedicated importer operation.
        elif args.command == "select-name":
            print("显示名称已更新，原有名称及选择依据已保留")
        # Dispatch the candidates command through its dedicated importer operation.
        elif args.command == "candidates":
            print(f"找到 {len(result)} 个候选实体")
            labels = {"same": "身份一致", "possible": "匹配结果待确认", "distinct": "身份不同", "similar": "类似工艺", "conflict": "匹配信息冲突"}
            # Show each retrieved candidate with its verdict and source assertion identifiers.
            for item in result:
                # Use '已入库' when item location equals 'accepted'; otherwise use '暂存'.
                location = "已入库" if item["location"] == "accepted" else "暂存"
                print(f"{location} · {TABLE_NAMES[item['table']]} · {item['id']} · "
                      f"{labels[item['comparison']['verdict']]}")
                print("来源记录与比对字段：")
                # Build mapped values from ('data', 'supporting_stage_ids').
                print(json_text({key: item[key] for key in ("data", "supporting_stage_ids")}))
            print("完整比对详情可用 --json candidates 查看")
        # Otherwise, report this outcome to the command-line operator.
        else:
            print("原始记录、规范化记录、质检详情与来源资料（原文及机器字段保持原样）：")
            print(json_text(result))
        return 0
    # Translate filesystem, validation, and database failures into a nonzero CLI exit and an
    # actionable message.
    except (OSError, ValueError, psycopg.Error) as exc:
        # Give connection failures a configuration-focused message without printing credentials.
        if isinstance(exc, psycopg.OperationalError):
            parser.exit(1, "数据库连接失败，请检查 PGHOST、PGPORT、PGDATABASE、PGUSER 和 PGPASSWORD。\n")
        # Use f'操作未完成：{exc}\n' when args.json; otherwise use '操作未完成，请检查记录编号、参数、文件或数据库版本；使用 --json
        # 可查看技术详情。\n'.
        parser.exit(1, f"操作未完成：{exc}\n" if args.json else
                    "操作未完成，请检查记录编号、参数、文件或数据库版本；使用 --json 可查看技术详情。\n")


# Run the command only when invoked as a script, not when imported by tests or other modules.
if __name__ == "__main__":
    raise SystemExit(main())
