"""Google Patents Public Datasets downloader —— BigQuery 查询结果落 JSONL。

与另外三个 downloader 不同，本源需要凭证：
  GOOGLE_APPLICATION_CREDENTIALS  服务账号 JSON 的路径
  GCP_BILLING_PROJECT             计费项目 id（BigQuery 即使查公开数据集也要计费项目）
外加 pip 包 google-cloud-bigquery。

2026-08-21 实测本机三者皆无（无 gcloud/bq CLI、无 google-cloud-bigquery、
.env 里无 GCP 相关键），所以这条 route 目前跑不通，会抛 MissingCredentials
并把缺什么、怎么补写清楚 —— 不做静默降级。

另需注意能力边界：BigQuery 的专利表给的是著录项与全文文本
（title / abstract / claims / description），不是 ST.25/ST.26 序列表。
能不能从中拿到 VH/VL 氨基酸序列尚未验证，见 registry 的 notes。
"""
from __future__ import annotations

import json
import os

from .base import MissingCredentials, Registry, Route, Snapshot

CREDENTIAL_ENV_DEFAULT = "GOOGLE_APPLICATION_CREDENTIALS"
PROJECT_ENV_DEFAULT = "GCP_BILLING_PROJECT"


def _client(credential_env: str, project_env: str):
    missing = []
    cred = os.getenv(credential_env)
    if not cred:
        missing.append(f"{credential_env}（服务账号 JSON 的绝对路径）")
    elif not os.path.isfile(cred):
        missing.append(f"{credential_env} 指向的档案不存在：{cred}")
    project = os.getenv(project_env)
    if not project:
        missing.append(f"{project_env}（启用了计费的 GCP 项目 id）")

    try:
        from google.cloud import bigquery  # noqa: PLC0415
    except ImportError:
        missing.append("pip 包 google-cloud-bigquery（requirements.txt 已列，需 pip install）")

    if missing:
        raise MissingCredentials(
            "Google Patents 走 BigQuery，缺下列前提，无法下载：\n  - "
            + "\n  - ".join(missing)
            + "\n\n补齐方式：把服务账号 JSON 放到本机，然后在 .env 里加两行——\n"
            f"  {credential_env}=/abs/path/to/service-account.json\n"
            f"  {project_env}=your-gcp-project-id\n"
            "并在 venv 里 pip install google-cloud-bigquery。\n"
            "注意 BigQuery 查询按扫描量计费，公开数据集也一样走你的计费项目。"
        )
    return bigquery.Client(project=project)


def run(reg: Registry, route: Route, snap: Snapshot, *, limit: int | None = None,
        dry_run: bool = False) -> None:
    sql = route.require("sql")
    auth = reg.download_config.get("auth") or {}
    credential_env = auth.get("credential_env", CREDENTIAL_ENV_DEFAULT)
    project_env = auth.get("billing_project_env", PROJECT_ENV_DEFAULT)

    output = route.get("output") or {}
    rows_file = output.get("rows", f"{route.route_id}.jsonl")
    sql_file = output.get("sql", f"{route.route_id}_query.sql")

    if limit:
        sql = f"SELECT * FROM (\n{sql}\n) LIMIT {int(limit)}"

    # SQL 先留证：即便查询失败，也要能看出这次打算查什么。
    snap.write_bytes(sql_file, sql.encode("utf-8"), note="本次提交的 BigQuery SQL")

    if dry_run:
        print("  [dry-run] 将提交的 SQL：")
        print("    " + sql.replace("\n", "\n    "))
        return

    client = _client(credential_env, project_env)
    print(f"  提交 BigQuery 查询（计费项目 {os.getenv(project_env)}）…")
    job = client.query(sql)
    rows = job.result()

    path = snap.path(rows_file)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dict(row), ensure_ascii=False, default=str) + "\n")
            n += 1
    snap.adopt(rows_file, note=f"{n} 行；扫描 {job.total_bytes_processed or 0:,} bytes")
    print(f"  取回 {n:,} 行，扫描 {job.total_bytes_processed or 0:,} bytes")
