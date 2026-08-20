"""PostgreSQL 连接、DDL 执行与批次管理。"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg

from .config import ROOT, settings


@contextmanager
def connect(autocommit: bool = False) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(settings.dsn, autocommit=autocommit)
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def apply_ddl(sql_dir: Path | None = None) -> list[str]:
    """按文件名顺序执行 sql/ 下的建表脚本。

    脚本全部写成 IF NOT EXISTS / DO 块，可反复执行 —— Day5-13 Schema 还会改，
    需要能整库删掉重建（sql/99_drop_all.sql）。
    """
    sql_dir = sql_dir or ROOT / "sql"
    applied: list[str] = []
    files = sorted(p for p in sql_dir.glob("*.sql") if not p.name.startswith("99_"))
    with connect(autocommit=True) as conn:
        for path in files:
            conn.execute(path.read_text(encoding="utf-8"))
            applied.append(path.name)
    return applied


def drop_all(sql_dir: Path | None = None) -> None:
    """整库删除，仅开发期使用。"""
    sql_dir = sql_dir or ROOT / "sql"
    with connect(autocommit=True) as conn:
        conn.execute((sql_dir / "99_drop_all.sql").read_text(encoding="utf-8"))


@contextmanager
def batch(stage: str, target: str, notes: str | None = None) -> Iterator[uuid.UUID]:
    """批次上下文：入库/抽取都在批次里跑，失败可按 batch_id 定位重跑。

        with batch("extract", "binder") as bid:
            ...  # 所有写入带上 batch_id=bid
    """
    batch_id = uuid.uuid4()
    with connect() as conn:
        conn.execute(
            "INSERT INTO core.batch_run (batch_id, stage, target, notes) VALUES (%s,%s,%s,%s)",
            (batch_id, stage, target, notes),
        )
    ok = True
    try:
        yield batch_id
    except Exception:
        ok = False
        raise
    finally:
        with connect() as conn:
            conn.execute(
                "UPDATE core.batch_run SET finished_at=now(), status=%s WHERE batch_id=%s",
                ("done" if ok else "failed", batch_id),
            )


def kpi() -> dict:
    """当前数量指标，对应跟踪表「5.数量指标KPI」。"""
    with connect() as conn:
        cur = conn.execute("SELECT * FROM qc.kpi")
        cols = [d.name for d in cur.description]
        return dict(zip(cols, cur.fetchone()))
