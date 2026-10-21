"""Raw Data 目录规范与来源登记。

目录约定（Day3 产出）：
    data/raw/<source>/<snapshot>/<file>
其中 <snapshot> 是上游版本号；上游没有固定版本的源（DOTAD、Google Patents）
用下载日期 YYYYMMDD 代替 —— 这些源不承诺更新周期，只能按我们自己的快照锁定版本。

每个文件落盘后写一条 core.source_registry：Day14 的引用可追溯性检查依赖它。
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from .config import settings
from .db import connect


def raw_dir(source: str, snapshot: str | None = None) -> Path:
    """返回（并创建）某数据源某快照的目录。"""
    # Prefer snapshot; if empty or absent, fall back to date.today().strftime('%Y%m%d').
    snapshot = snapshot or date.today().strftime("%Y%m%d")
    path = settings.data_root / "raw" / source / snapshot
    path.mkdir(parents=True, exist_ok=True)
    return path


# Hash file contents incrementally so large downloads do not need to fit in memory.
def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    # Close the file reliably, including when reading or writing raises an error.
    with path.open("rb") as fh:
        # Read bounded chunks until EOF to avoid loading the whole file into memory.
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def register(
    *,
    source_name: str,
    local_path: Path,
    used_for: str | None = None,
    owner: str | None = None,
    api_endpoint: str | None = None,
    file_format: str | None = None,
    snapshot_version: str | None = None,
    record_count: int | None = None,
    notes: str | None = None,
) -> int:
    """登记一个已下载的原始文件，返回 registry_id。"""
    local_path = Path(local_path)
    # Stop rather than continue with invalid or incomplete input.
    if not local_path.exists():
        raise FileNotFoundError(local_path)
    # Prefer snapshot_version; if empty or absent, fall back to date.today().strftime('%Y%m%d').
    snapshot_version = snapshot_version or date.today().strftime("%Y%m%d")
    # Close the database connection when this operation finishes or raises.
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO core.source_registry
              (source_name, used_for, owner, api_endpoint, file_format,
               snapshot_version, local_path, sha256, record_count, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source_name, snapshot_version, local_path) DO UPDATE
              SET sha256 = EXCLUDED.sha256,
                  record_count = EXCLUDED.record_count,
                  downloaded_at = now()
            RETURNING id
            """,
            (source_name, used_for, owner, api_endpoint, file_format,
             snapshot_version, str(local_path), sha256(local_path),
             record_count, notes),
        )
        return cur.fetchone()[0]
