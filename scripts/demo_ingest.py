#!/usr/bin/env python3
"""Run a synthetic ingestion demonstration in a newly created, isolated database.

Uses PG* environment settings. The connecting role needs CREATE DATABASE.
The new database is retained for inspection; existing databases are not modified.
"""
from pathlib import Path
import sys
from uuid import uuid4

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cart_db import ingest
from cart_db.console import count_text
from cart_db.ingest_schema import migrate


def main():
    name = "cart_import_demo_" + uuid4().hex[:12]
    with ingest.connect() as admin:
        params = admin.info.get_parameters()
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    # get_parameters intentionally omits passwords; use the original configuration.
    params["password"] = ingest.settings.pg_password
    params["dbname"] = name
    examples = Path(__file__).resolve().parents[1] / "examples" / "database_import"
    print(f"合成数据演示数据库： {name}")
    with psycopg.connect(**params, autocommit=True) as conn:
        migrate(conn)
        for filename in ("01_existing.jsonl", "02_new_paper.jsonl", "03_incomplete.jsonl"):
            batch = ingest.stage_file(conn, examples / filename)
            report = ingest.publish(conn, batch)
            binders = conn.execute("SELECT count(*) FROM cart.binder").fetchone()[0]
            evidence = conn.execute("SELECT count(*) FROM cart.evidence").fetchone()[0]
            print(f"{filename}: {count_text(report['counts'])}；库中结合域 {binders} 条，证据 {evidence} 条")
            if filename == "01_existing.jsonl":
                assert (binders, evidence) == (2, 1)
            elif filename == "02_new_paper.jsonl":
                assert (binders, evidence) == (2, 2)
                # Reimporting the identical file cannot add another observation.
                assert ingest.stage_file(conn, examples / filename) == batch
                ingest.publish(conn, batch)
                assert conn.execute("SELECT count(*) FROM cart.evidence").fetchone()[0] == 2
            else:
                assert report["counts"]["published"] == 2
                assert report["identity_counts"]["unresolved"] == 1
                assert (binders, evidence) == (3, 3)
                incoming = next(r for r in report["records"] if r["table_name"] == "binder")
                matches = ingest.candidates(conn, incoming["stage_id"])
                assert len(matches) == 2
                print(f"  信息不完整的结合域：找到 {len(matches)} 个可能匹配，已独立入库，标记匹配结果待确认。")
                print(f"  匹配结果待确认批次： {batch}")
                print(f"  匹配结果待确认来源记录： {incoming['stage_id']}")
        print("收集到的名称：")
        for (names,) in conn.execute("SELECT array_agg(DISTINCT name ORDER BY name) FROM cart.entity_name GROUP BY entity_id ORDER BY min(name)"):
            print("  " + ", ".join(names))
        print("两篇文献的观测值分别保留：2 nM 和 3 nM。")
        print("本演示使用短合成序列验证程序流程，不用于评价真实文献提取效果。")
    print(f"查看结果：PGDATABASE={name} python -m cart_db.ingest status <批次编号>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
