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


def connect():
    return psycopg.connect(host=settings.pg_host, port=settings.pg_port,
                          dbname=settings.pg_database, user=settings.pg_user,
                          password=settings.pg_password, autocommit=True, connect_timeout=5)


def rows(conn, query, params=()):
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def accepted(conn, table, record_id):
    query = sql.SQL("SELECT to_jsonb(t) - 'record_kind' AS data FROM cart.{} t WHERE {}=%s").format(
        sql.Identifier(table), sql.Identifier(primary_key(table)))
    found = rows(conn, query, (record_id,))
    if not found:
        raise ValueError(f"No accepted {table} record: {record_id}")
    data = found[0]["data"]
    return {name: data[column(name)] for name in load_schema().tables[table]}


def accepted_id(conn, table, value):
    try:
        value = UUID(str(value))
    except (ValueError, TypeError):
        return None
    found = conn.execute("SELECT record_id FROM cart.record WHERE record_id=%s AND table_name=%s",
                         (value, table)).fetchone()
    return found[0] if found else None


def _references(table):
    return [(name, spec["references"].split(".")[0])
            for name, spec in load_schema().tables[table].items() if spec.get("key") == "foreign"]


def stage_file(conn, path, contexts=(), on_status=None):
    """Record even rejected rows. Local IDs are scoped to this immutable batch."""
    path = Path(path)
    notify = on_status or (lambda message: None)
    notify("正在读取 JSONL，规范化序列和计量单位，并校验字段")
    content = path.read_bytes()
    input_text = content.decode("utf-8")
    checksum = hashlib.sha256(content).hexdigest()
    batch_id = uuid5(NAMESPACE_URL, "cart-import:" + checksum)
    staged = []
    for line_no, line in enumerate(input_text.splitlines(), 1):
        if not line.strip():
            continue
        row = dict(stage_id=uuid5(batch_id, str(line_no)), line_number=line_no,
                   table_name=None, local_id=None, original=None, normalized=None, audit=[], errors=[])
        try:
            def invalid_constant(value):
                raise OutputError(f"Non-finite JSON number: {value}")

            def finite_float(value):
                number = float(value)
                if not math.isfinite(number):
                    invalid_constant(value)
                return number

            item = json.loads(line, object_pairs_hook=_unique_object,
                              parse_constant=invalid_constant, parse_float=finite_float)
            row["original"] = item
            if not isinstance(item, dict) or set(item) != {"table", "data"}:
                raise OutputError("Expected exactly table and data")
            table = item["table"]
            if not isinstance(table, str) or table not in TABLES:
                raise OutputError("Unknown table")
            row["table_name"] = table
            # Reserve even a rejected row's declared label. It must not silently
            # fall through to an accepted UUID of the same spelling.
            if isinstance(item["data"], dict):
                local_id = item["data"].get(primary_key(table))
                if isinstance(local_id, str):
                    row["local_id"] = local_id
            data, audit = normalize_record(table, item["data"])
            row.update(local_id=data[primary_key(table)], normalized=data, audit=audit)
            if table == "evidence":
                owners = [e for e in load_schema().entities if data[e.fk_column] is not None]
                if not owners:
                    raise OutputError("Evidence must reference at least one entity")
                for entity in load_schema().entities:
                    if entity not in owners and any(v is not None for k, v in data.items()
                                                    if k.startswith(entity.kind + ".")):
                        raise OutputError(f"{entity.kind} fields without an entity reference")
        except (ValueError, TypeError, KeyError) as exc:
            row["errors"].append(str(exc))
        staged.append(row)

    # Read contexts before opening the transaction, so missing files cannot leave a partial batch.
    context_data = [(Path(p).name, Path(p).read_text(encoding="utf-8")) for p in contexts]
    with conn.transaction():
        notify("正在核对记录引用，并保存原始记录、规范化结果和质检问题")
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        check_contract(conn)
        existing = conn.execute("SELECT batch_id,schema_hash FROM cart.import_batch WHERE checksum=%s",
                                (checksum,)).fetchone()
        by_local = {}
        for row in staged:
            if row["local_id"] is not None:
                by_local.setdefault((row["table_name"], row["local_id"]), []).append(row)
        for duplicates in by_local.values():
            if len(duplicates) > 1:
                for row in duplicates:
                    row["errors"].append("Duplicate local ID within input table")
        # Propagate invalid dependencies until all dependants have been marked.
        changed = True
        while changed:
            changed = False
            for row in staged:
                if row["errors"]:
                    continue
                for field, target in _references(row["table_name"]):
                    value = row["normalized"][field]
                    if value is None:
                        continue
                    local = by_local.get((target, value))
                    if ((local and any(r["errors"] for r in local))
                            or (not local and not accepted_id(conn, target, value))):
                        row["errors"].append(f"Unresolved or invalid reference {field}: {value}")
                        changed = True
                        break
        if not existing:
            conn.execute("""INSERT INTO cart.import_batch
                (batch_id,checksum,input_name,input_text,schema_hash) VALUES (%s,%s,%s,%s,%s)""",
                         (batch_id, checksum, str(path.resolve()), input_text, contract_hash()))
            for row in staged:
                conn.execute("""INSERT INTO cart.staged_record
                    (stage_id,batch_id,line_number,table_name,local_id,original,normalized,audit,errors,status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (row["stage_id"], batch_id, row["line_number"], row["table_name"], row["local_id"],
                     Jsonb(row["original"]) if row["original"] is not None else None,
                     Jsonb(row["normalized"]) if row["normalized"] is not None else None,
                     Jsonb(row["audit"]), Jsonb(row["errors"]), "invalid" if row["errors"] else "pending"))
                if not row["errors"] and row["table_name"] in ENTITIES:
                    for basis, fingerprint, value in features(row["table_name"], row["normalized"]):
                        conn.execute("""INSERT INTO cart.identity_feature(stage_id,basis,fingerprint,value)
                            VALUES (%s,%s,%s,%s)""", (row["stage_id"], basis, fingerprint, Jsonb(value)))
        elif existing[1] != contract_hash():
            previous = {str(r["stage_id"]): r for r in rows(conn,
                "SELECT * FROM cart.staged_record WHERE batch_id=%s", (batch_id,))}
            for row in staged:
                old = previous[str(row["stage_id"])]
                if old["status"] == "published":
                    continue
                audit = [dict(reason="previous_schema_validation", before={
                    "schema_hash": existing[1], "normalized": old["normalized"],
                    "audit": old["audit"], "errors": old["errors"]}, after=None), *row["audit"]]
                conn.execute("""UPDATE cart.staged_record SET normalized=%s,audit=%s,errors=%s,status=%s
                    WHERE stage_id=%s""", (Jsonb(row["normalized"]), Jsonb(audit), Jsonb(row["errors"]),
                        "invalid" if row["errors"] else "pending", row["stage_id"]))
                conn.execute("DELETE FROM cart.identity_feature WHERE stage_id=%s", (row["stage_id"],))
                if not row["errors"] and row["table_name"] in ENTITIES:
                    for basis, fingerprint, value in features(row["table_name"], row["normalized"]):
                        conn.execute("INSERT INTO cart.identity_feature(stage_id,basis,fingerprint,value) VALUES (%s,%s,%s,%s)",
                                     (row["stage_id"], basis, fingerprint, Jsonb(value)))
            conn.execute("UPDATE cart.import_batch SET schema_hash=%s WHERE batch_id=%s", (contract_hash(), batch_id))
        for name, text in context_data:
            conn.execute("""INSERT INTO cart.import_context(batch_id,name,checksum,content)
                VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                         (batch_id, name, hashlib.sha256(text.encode()).hexdigest(), text))
    return batch_id


def get_stage(conn, stage_id):
    found = rows(conn, "SELECT * FROM cart.staged_record WHERE stage_id=%s", (stage_id,))
    if not found:
        raise ValueError(f"Unknown staging record: {stage_id}")
    return found[0]


def candidates(conn, stage_id):
    """Return candidate claims and accepted entities, without transitive grouping."""
    row = get_stage(conn, stage_id)
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
    for other in found:
        target = other["target_id"]
        key = ("accepted", str(target)) if target else ("staging", str(other["stage_id"]))
        if key in result:
            continue
        data = accepted(conn, row["table_name"], target) if target else other["normalized"]
        claims = rows(conn, "SELECT stage_id,normalized FROM cart.staged_record WHERE target_id=%s ORDER BY stage_id",
                      (target,)) if target else [other]
        comparisons = [compare(row["table_name"], row["normalized"], data)]
        if target:
            comparisons.extend(compare(row["table_name"], row["normalized"], claim["normalized"])
                               for claim in claims)
        verdicts = {c["verdict"] for c in comparisons}
        conflicts = sorted({field for c in comparisons for field in c.get("conflicts", [])})
        if "conflict" in verdicts or {"same", "distinct"} <= verdicts:
            comparison = dict(verdict="conflict", conflicts=conflicts,
                              reason="来源记录之间存在明确的身份冲突，禁止自动合并。")
        elif conflicts:
            comparison = dict(verdict="possible", conflicts=conflicts,
                              reason="来源注释存在差异，需要核查。")
        elif "same" in verdicts:
            comparison = next(c for c in comparisons if c["verdict"] == "same")
        elif "similar" in verdicts:
            comparison = next(c for c in comparisons if c["verdict"] == "similar")
        elif verdicts == {"distinct"}:
            comparison = comparisons[0]
        else:
            comparison = next(c for c in comparisons if c["verdict"] == "possible")
        result[key] = dict(location=key[0], id=key[1], table=row["table_name"], data=data,
                           supporting_stage_ids=[str(claim["stage_id"]) for claim in claims],
                           comparison=comparison)
    return sorted(result.values(), key=lambda r: (r["location"], r["id"]))


def decide(conn, stage_id, action, reviewer, reason, target_id=None, target_stage_id=None):
    """Persist a reviewer decision. It takes effect only during publication."""
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Reviewer and source-based reason are required")
    if action not in ("new", "link") or ((target_id is not None) + (target_stage_id is not None)) != (action == "link"):
        raise ValueError("new needs no target; link needs exactly one target")
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        check_contract(conn)
        row = get_stage(conn, stage_id)
        if row["status"] != "pending":
            raise ValueError("Only pending records can receive identity decisions")
        if target_id and not accepted_id(conn, row["table_name"], target_id):
            raise ValueError("Target must be an accepted record of the same table")
        if target_stage_id:
            other = get_stage(conn, target_stage_id)
            if other["table_name"] != row["table_name"] or other["status"] == "invalid":
                raise ValueError("Target staging record must be valid and of the same table")
            seen = {str(stage_id)}
            current = str(target_stage_id)
            while current:
                if current in seen:
                    raise ValueError("Cyclic staging identity decisions")
                seen.add(current)
                previous = conn.execute("""SELECT target_stage_id FROM cart.identity_decision
                    WHERE stage_id=%s ORDER BY decision_id DESC LIMIT 1""", (current,)).fetchone()
                current = str(previous[0]) if previous and previous[0] else None
        conn.execute("""INSERT INTO cart.identity_decision
            (stage_id,action,target_id,target_stage_id,reviewer,reason) VALUES (%s,%s,%s,%s,%s,%s)""",
                     (stage_id, action, target_id, target_stage_id, reviewer, reason))


def _insert_record(conn, table, data):
    fields = load_schema().tables[table]
    record_id = data[primary_key(table)]
    conn.execute("INSERT INTO cart.record(record_id,table_name) VALUES (%s,%s)", (record_id, table))
    values = [Jsonb(data[name]) if data[name] is not None and spec["type"] in ("json", "measurement")
              else data[name] for name, spec in fields.items()]
    conn.execute(sql.SQL("INSERT INTO cart.{} ({}) VALUES ({})").format(
        sql.Identifier(table), sql.SQL(",").join(sql.Identifier(column(name)) for name in fields),
        sql.SQL(",").join(sql.Placeholder() for _ in fields)), values)
    return record_id


def _finish(conn, row, target, method, details):
    details = {"comparison_policy": "source-admission-v3", **details}
    conn.execute("""UPDATE cart.staged_record SET status='published',target_id=%s,published_at=now(),
        identity_status=%s,identity_details=%s WHERE stage_id=%s""",
        (target, details.get("identity_status", "resolved") if row["table_name"] in ENTITIES else None,
         Jsonb(details) if row["table_name"] in ENTITIES else None, row["stage_id"]))
    conn.execute("INSERT INTO cart.publication_log(stage_id,target_id,method,details) VALUES (%s,%s,%s,%s)",
                 (row["stage_id"], target, method, Jsonb(details)))
    if row["table_name"] in ENTITIES:
        data = row["normalized"]
        for name in [data.get("name"), *(data.get("aliases") or [])]:
            if isinstance(name, str) and name.strip():
                conn.execute("""INSERT INTO cart.entity_name(entity_id,name,stage_id)
                    VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""", (target, name, row["stage_id"]))


def _mapped_data(conn, row):
    # New optional fields remain unknown for staging records saved before migration.
    data = {field: deepcopy(row["normalized"].get(field))
            for field in load_schema().tables[row["table_name"]]}
    for field, table in _references(row["table_name"]):
        value = data[field]
        if value is None:
            continue
        local = rows(conn, """SELECT status,target_id FROM cart.staged_record
            WHERE batch_id=%s AND table_name=%s AND local_id=%s""", (row["batch_id"], table, value))
        if local:
            if len(local) != 1 or local[0]["status"] != "published":
                return None
            target = local[0]["target_id"]
        else:
            target = accepted_id(conn, table, value)
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
    notify = on_status or (lambda message: None)
    notify("正在比对实体，确定复用或新增，并重写组合和证据引用")
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        check_contract(conn)
        progress = True
        while progress:
            progress = False
            pending = rows(conn, """SELECT * FROM cart.staged_record WHERE batch_id=%s AND status='pending'
                ORDER BY CASE table_name WHEN 'binder' THEN 1 WHEN 'car' THEN 2
                  WHEN 'manufacturing' THEN 3 WHEN 'abc_combination_db1' THEN 4 ELSE 5 END,line_number""",
                           (batch_id,))
            for row in pending:
                stage_id, table = row["stage_id"], row["table_name"]
                key = str(stage_id)
                decisions = rows(conn, """SELECT * FROM cart.identity_decision WHERE stage_id=%s
                    ORDER BY decision_id DESC LIMIT 1""", (stage_id,))
                decision = decisions[0] if decisions else None
                target, method, details = None, "", {}
                if decision:
                    details = dict(decision_id=decision["decision_id"], reviewer=decision["reviewer"],
                                   reason=decision["reason"])
                    method = "reviewed_" + decision["action"]
                    if decision["action"] == "link":
                        target = decision["target_id"]
                        if decision["target_stage_id"]:
                            target = get_stage(conn, decision["target_stage_id"])["target_id"]
                        if not target:
                            pending_reasons[key] = "Reviewed target is still pending"
                            continue
                        # Even reviewed observation links must retain the same mapped owners.
                        if table not in ENTITIES:
                            mapped = _mapped_data(conn, row)
                            if mapped is None:
                                pending_reasons[key] = "Dependent entity or combination is pending"
                                continue
                            existing = accepted(conn, table, target)
                            if any(mapped[f] != existing[f] for f, _ in _references(table)):
                                raise ValueError("Reviewed link has conflicting resolved references")
                if table in ENTITIES and target is None:
                    matches = candidates(conn, stage_id)
                    same = [m for m in matches if m["location"] == "accepted" and m["comparison"]["verdict"] == "same"]
                    conflicts = [m for m in matches if m["comparison"]["verdict"] == "conflict"]
                    possible = [m for m in matches if m["comparison"]["verdict"] == "possible"
                                and (m["location"] == "accepted" or strong_key(table, m["data"])
                                     or m["comparison"].get("conflicts"))]
                    similar = [m for m in matches if m["comparison"]["verdict"] == "similar"]
                    flags = [e for e in row["audit"] if e["reason"].startswith("review_")]
                    if decision and same:
                        pending_reasons[key] = "Reviewed new entity now has an exact accepted match; review again"
                        continue
                    if not decision:
                        if len(same) == 1 and not conflicts and not possible and not flags:
                            target, method = same[0]["id"], "exact_identity"
                            details = same[0]["comparison"]
                        else:
                            identity_status = ("conflict" if conflicts else "unresolved" if
                                possible or len(same) > 1 or flags else "similar" if similar else
                                "resolved")
                            method = "new_complete_identity" if identity_status == "resolved" and strong_key(table, row["normalized"]) else "new_source_entity"
                            details = dict(identity_status=identity_status,
                                reason="保存来源实体；身份是否重复与数据入库分别处理。",
                                candidates=[{k: m[k] for k in ("location", "id", "comparison", "supporting_stage_ids")}
                                            for m in matches if m["comparison"]["verdict"] != "distinct"],
                                normalization_flags=flags)
                if target is None:
                    data = _mapped_data(conn, row)
                    if data is None:
                        pending_reasons[key] = "Dependent entity or combination is pending"
                        continue
                    if table == "abc_combination_db1":
                        existing = conn.execute("""SELECT combination_id FROM cart.abc_combination_db1
                            WHERE binder_id=%s AND car_id=%s AND manufacturing_id=%s""",
                            (data["binder_id"], data["car_id"], data["manufacturing_id"])).fetchone()
                        if existing:
                            target, method = existing[0], "existing_abc_combination"
                    if table == "evidence" and data["combination_id"]:
                        combo = accepted(conn, "abc_combination_db1", data["combination_id"])
                        if any(data[e.fk_column] is not None and data[e.fk_column] != combo[e.id_column]
                               for e in load_schema().entities):
                            pending_reasons[key] = "Resolved evidence references disagree with its ABC combination"
                            continue
                    if target is None:
                        data[primary_key(table)] = str(uuid4())
                        target = _insert_record(conn, table, data)
                        method = method or "new_source_observation_or_combination"
                _finish(conn, row, target, method, details)
                pending_reasons.pop(key, None)
                progress = True
        notify("正在检查数据库约束并提交本批次可确定的记录")
    result = batch_status(conn, batch_id)
    result["pending_reasons"] = pending_reasons
    return result


def batch_status(conn, batch_id):
    if not conn.execute("SELECT 1 FROM cart.import_batch WHERE batch_id=%s", (batch_id,)).fetchone():
        raise ValueError("Unknown import batch")
    records = rows(conn, """SELECT stage_id,line_number,table_name,local_id,status,target_id,errors,audit,identity_status,identity_details
        FROM cart.staged_record WHERE batch_id=%s ORDER BY line_number""", (batch_id,))
    counts = {status: sum(r["status"] == status for r in records) for status in ("published", "pending", "invalid")}
    identity_counts = {state: sum(r["identity_status"] == state for r in records)
                       for state in ("resolved", "unresolved", "similar", "conflict")}
    return dict(batch_id=str(batch_id), counts=counts, identity_counts=identity_counts, records=records)


def select_name(conn, entity_id, name, selector, reason):
    """Accept a human/Jev selection from collected names; do not call a model."""
    if not selector.strip() or not reason.strip():
        raise ValueError("Selector (including model/version) and reason are required")
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        check_contract(conn)
        record = conn.execute("SELECT table_name FROM cart.record WHERE record_id=%s", (entity_id,)).fetchone()
        if not record or record[0] not in ENTITIES:
            raise ValueError("Name selection requires an accepted entity")
        if not conn.execute("SELECT 1 FROM cart.entity_name WHERE entity_id=%s AND name=%s", (entity_id, name)).fetchone():
            raise ValueError("Selected name must be an existing source-reported name")
        conn.execute(sql.SQL("UPDATE cart.{} SET name=%s WHERE {}=%s").format(
            sql.Identifier(record[0]), sql.Identifier(primary_key(record[0]))), (name, entity_id))
        if record[0] == "binder":
            aliases = [r[0] for r in conn.execute("""SELECT DISTINCT name FROM cart.entity_name
                WHERE entity_id=%s AND name<>%s ORDER BY name""", (entity_id, name))]
            conn.execute("UPDATE cart.binder SET aliases=%s WHERE binder_id=%s", (Jsonb(aliases), entity_id))
        conn.execute("INSERT INTO cart.name_selection(entity_id,name,selector,reason) VALUES (%s,%s,%s,%s)",
                     (entity_id, name, selector, reason))


def export_records(conn):
    """Accepted five-table JSONL; source assertions remain separately in staging."""
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        check_contract(conn)
        result = []
        for table in TABLES:
            for (record_id,) in conn.execute("SELECT record_id FROM cart.record WHERE table_name=%s ORDER BY record_id", (table,)):
                result.append(dict(table=table, data=accepted(conn, table, record_id)))
        return result


def main(argv=None):
    parser = ChineseArgumentParser(description="JSONL 规范化、质检、实体比对与 PostgreSQL 入库")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON，保留字段和状态代码")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="在 cart 中执行增量数据库迁移")
    stage = commands.add_parser("stage", help="规范化、质检并暂存一个 JSONL 文件")
    stage.add_argument("path", type=Path)
    stage.add_argument("--context", type=Path, action="append", default=[], help="保存来源依据、异常和追溯文件")
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
    try:
        with connect() as conn:
            if args.command == "migrate":
                migrate(conn)
                result = {"migrations": "applied"}
            elif args.command == "stage":
                result = batch_status(conn, stage_file(conn, args.path, args.context))
            elif args.command == "status":
                result = batch_status(conn, args.batch_id)
            elif args.command == "publish":
                result = publish(conn, args.batch_id)
            elif args.command == "candidates":
                result = candidates(conn, args.stage_id)
            elif args.command == "inspect":
                result = get_stage(conn, args.stage_id)
                result["context"] = rows(conn, "SELECT name,content FROM cart.import_context WHERE batch_id=%s ORDER BY name,checksum",
                                         (result["batch_id"],))
            elif args.command == "decide":
                decide(conn, args.stage_id, args.action, args.reviewer, args.reason, args.target_id, args.target_stage_id)
                result = {"decision": "recorded"}
            elif args.command == "select-name":
                select_name(conn, args.entity_id, args.name, args.selector, args.reason)
                result = {"name_selection": "recorded"}
            else:
                for record in export_records(conn):
                    print(dump(record))
                return 0
        if args.json:
            print(json_text(result))
        elif args.command in ("stage", "status", "publish"):
            print(report_text(result))
        elif args.command == "migrate":
            print("数据库迁移及字段版本核对完成")
        elif args.command == "decide":
            print("审核决定已保存；请再次运行 publish 完成入库")
        elif args.command == "select-name":
            print("显示名称已更新，原有名称及选择依据已保留")
        elif args.command == "candidates":
            print(f"找到 {len(result)} 个候选实体")
            labels = {"same": "身份一致", "possible": "匹配结果待确认", "distinct": "身份不同", "similar": "类似工艺", "conflict": "匹配信息冲突"}
            for item in result:
                location = "已入库" if item["location"] == "accepted" else "暂存"
                print(f"{location} · {TABLE_NAMES[item['table']]} · {item['id']} · "
                      f"{labels[item['comparison']['verdict']]}")
                print("来源记录与比对字段：")
                print(json_text({key: item[key] for key in ("data", "supporting_stage_ids")}))
            print("完整比对详情可用 --json candidates 查看")
        else:
            print("原始记录、规范化记录、质检详情与来源资料（原文及机器字段保持原样）：")
            print(json_text(result))
        return 0
    except (OSError, ValueError, psycopg.Error) as exc:
        if isinstance(exc, psycopg.OperationalError):
            parser.exit(1, "数据库连接失败，请检查 PGHOST、PGPORT、PGDATABASE、PGUSER 和 PGPASSWORD。\n")
        parser.exit(1, f"操作未完成：{exc}\n" if args.json else
                    "操作未完成，请检查记录编号、参数、文件或数据库版本；使用 --json 可查看技术详情。\n")


if __name__ == "__main__":
    raise SystemExit(main())
