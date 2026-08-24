"""Europe PMC downloader —— 检索 + 全文 XML。

两段式：
  1. /search 翻页（cursorMark），把 core 记录整批存下来 —— 这是文献元数据，
     供 docs/Mapping/europe_pmc_to_process.yaml 取 source_id / citation / license。
  2. 对 inEPMC=Y 的记录逐篇取 /{pmcid}/fullTextXML —— 工艺参数在正文里，
     moi / culture_days / vcn / mycoplasma 四个字段只能从这里抽。

全文端点的正确形态是 /{pmcid}/fullTextXML，不是 /PMC/{pmcid}/fullTextXML
（后者实测 404）。
"""
from __future__ import annotations

from .base import Fetcher, Registry, Route, Snapshot

SEARCH_FILE_DEFAULT = "search_results.json"
FULLTEXT_DIR_DEFAULT = "fulltext"


def _search(fetcher: Fetcher, endpoint: str, query: str, *, result_type: str,
            page_size: int, max_records: int) -> tuple[list[dict], int]:
    """cursorMark 翻页。Europe PMC 明确要求用 cursorMark 而非 offset。"""
    records: list[dict] = []
    cursor = "*"
    hit_count = 0
    while True:
        payload = fetcher.get_json(
            endpoint,
            params={
                "query": query,
                "format": "json",
                "resultType": result_type,
                "pageSize": page_size,
                "cursorMark": cursor,
            },
        )
        hit_count = payload.get("hitCount", 0)
        batch = payload.get("resultList", {}).get("result", [])
        if not batch:
            break
        records.extend(batch)
        next_cursor = payload.get("nextCursorMark")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        if max_records and len(records) >= max_records:
            records = records[:max_records]
            break
    return records, hit_count


def run(reg: Registry, route: Route, snap: Snapshot, *, limit: int | None = None,
        dry_run: bool = False) -> None:
    endpoint = route.require("search_endpoint")
    query = route.require("query")
    result_type = route.get("result_type", "core")
    page_size = int(route.get("page_size", 100))
    max_records = int(route.get("max_records") or 0)
    if limit:
        max_records = min(max_records, limit) if max_records else limit

    output = route.get("output") or {}
    search_file = output.get("search_results", SEARCH_FILE_DEFAULT)
    fulltext_dir = output.get("fulltext_dir", FULLTEXT_DIR_DEFAULT)
    fulltext_tpl = route.get("fulltext_endpoint")

    with Fetcher(reg.http) as fetcher:
        if dry_run:
            payload = fetcher.get_json(
                endpoint,
                params={"query": query, "format": "json", "resultType": "lite",
                        "pageSize": 1, "cursorMark": "*"},
            )
            print(f"  [dry-run] hitCount = {payload.get('hitCount')}，"
                  f"将抓取上限 {max_records or '全部'}")
            return

        records, hit_count = _search(
            fetcher, endpoint, query,
            result_type=result_type, page_size=page_size, max_records=max_records,
        )
        print(f"  检索命中 {hit_count}，取回 {len(records)} 条记录")
        snap.write_json(
            search_file,
            {"query": query, "result_type": result_type,
             "hit_count": hit_count, "retrieved": len(records), "records": records},
            url=endpoint,
            note="检索结果（文献元数据），全文见 fulltext/",
        )

        if not fulltext_tpl:
            return

        ok = resumed = 0
        for i, rec in enumerate(records, 1):
            pmcid = rec.get("pmcid")
            if not pmcid:
                snap.skip("no_pmcid", id=rec.get("id"), source=rec.get("source"))
                continue
            if rec.get("inEPMC") != "Y":
                # inEPMC=N 表示 Europe PMC 没有托管全文，只能拿到摘要。
                snap.skip("not_in_epmc", id=rec.get("id"), pmcid=pmcid)
                continue

            name = f"{fulltext_dir}/{pmcid}.xml"
            url = fulltext_tpl.format(pmcid=pmcid)
            if snap.done(name):
                snap.adopt(name, url=url, note="已存在，跳过")
                resumed += 1
                continue

            resp = fetcher.get(url)
            if resp.status_code != 200 or not resp.content:
                snap.skip(f"fulltext_http_{resp.status_code}", pmcid=pmcid, url=url)
                continue
            snap.write_bytes(name, resp.content, url=url)
            ok += 1
            if i % 200 == 0:
                print(f"    进度 {i}/{len(records)}：新增 {ok}，续传跳过 {resumed}，"
                      f"未取到 {len(snap.skipped)}")

        print(f"  全文：新增 {ok}，已存在 {resumed}，未取到 {len(snap.skipped)}")
