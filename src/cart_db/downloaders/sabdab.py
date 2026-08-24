"""SAbDab2 downloader —— 全量 summary CSV + 按靶点检索的结构档。

两类 route，对应两种取数粒度：

  all_summary        GET /api/download/all-summary
                     45 栏 × 21,914 行，实测 11.7 MB。全量拿，因为它就是索引本身：
                     不先有它，就无从判断某个靶点在库里到底有没有记录。summary 内不含序列。

  target_structures  POST /api/download/search-summary   → 命中子集 CSV
                     POST /api/download/search-structures → mmCIF 打包 .tgz
                     vh_sequence / vl_sequence 只能从 mmCIF 拿，summary 一个氨基酸都没有。
                     结构档体积大，所以只对本项目靶点下载 —— 业务侧 2026-08-24
                     「binder 数据库是要 GCC/CDH17 靶点相关的」。

坑（2026-08-24 实测）：binds_to_antigen 匹配的是 antigen_name 那一栏的文本，
不是基因符号。"guanylyl cyclase" 命中 3 条，"GUCY2C" 命中 0 条。
所以 registry 里的 queries 必须写抗原全名，且同一靶点要把别名都列上。

命中 0 条不是错误，是要留档的事实（实测 CDH17 在本库内确实是空集），
因此记为 skip 而非抛错，并跳过该 label 的结构档下载。
"""
from __future__ import annotations

import json

import httpx

from .base import DownloadError, Fetcher, Registry, Route, Snapshot

# 零命中时 SAbDab 回 404 而不是空 CSV，与「路径不存在」共用状态码，
# 只能靠响应体区分（2026-08-24 实测）：
#   零命中  {"detail":"No antibody instances matched the requested filters."}
#   路径错  {"detail":"Not Found"}
NO_HITS_DETAIL = "No antibody instances matched"


def _row_count(csv_bytes: bytes) -> int:
    """CSV 数据行数（扣掉表头）。空档或只有表头都算 0。"""
    lines = [ln for ln in csv_bytes.decode("utf-8", "replace").splitlines() if ln.strip()]
    return max(len(lines) - 1, 0)


def _post_or_none(fetcher: Fetcher, url: str, body: dict) -> bytes | None:
    """POST 检索；零命中回 None。其余错误照常抛出，不吞。"""
    try:
        return fetcher.post_bytes(url, json=body)
    except httpx.HTTPStatusError as exc:
        r = exc.response
        if r.status_code == 404 and NO_HITS_DETAIL in r.text:
            return None
        raise


def _all_summary(reg: Registry, route: Route, snap: Snapshot, dry_run: bool) -> None:
    endpoint = route.require("endpoint")
    name = (route.get("output") or {}).get("summary", "all_summary.csv")

    if dry_run:
        print(f"    [dry-run] GET {endpoint} → {name}")
        return
    if snap.done(name):
        snap.adopt(name, url=endpoint, note="已存在，跳过")
        print(f"    已存在，跳过  {name}")
        return

    with Fetcher(reg.http) as fetcher:
        size = fetcher.stream_to(endpoint, snap.path(name))
    rows = _row_count(snap.path(name).read_bytes())
    snap.adopt(name, url=endpoint, note=f"全量 antibody instance summary，{rows:,} 行")
    print(f"    {size:>12,} bytes  {name}（{rows:,} 行）")


def _target_structures(reg: Registry, route: Route, snap: Snapshot,
                       limit: int | None, dry_run: bool) -> None:
    summary_ep = route.require("search_summary_endpoint")
    structures_ep = route.require("search_structures_endpoint")
    queries = route.require("queries")
    if limit:
        queries = queries[:limit]

    if dry_run:
        for q in queries:
            print(f"    [dry-run] {q['label']:10s} POST {json.dumps(q['body'], ensure_ascii=False)}")
        return

    hit_labels = 0
    with Fetcher(reg.http) as fetcher:
        for q in queries:
            label, body = q["label"], q["body"]

            csv_bytes = _post_or_none(fetcher, summary_ep, body)
            rows = _row_count(csv_bytes) if csv_bytes else 0

            if rows == 0:
                # 空集是结论，不是失败。留档以免下一个人重复检索。
                # 不写空 CSV：磁盘上一个 0 行的档比 manifest 里一条 skip 更容易被误读成「下载坏了」。
                snap.skip("no_hits", label=label, query=body,
                          note="该靶点在 SAbDab2 内无记录，非下载失败")
                print(f"    {label:12s} 无命中，跳过结构档")
                continue

            snap.write_bytes(f"{label}_summary.csv", csv_bytes, url=summary_ep,
                             note=f"检索条件 {json.dumps(body, ensure_ascii=False)}；{rows} 行")
            print(f"    {label:12s} summary  {rows:>4} 行")

            tgz_name = f"{label}_structures.tgz"
            if snap.done(tgz_name):
                snap.adopt(tgz_name, url=structures_ep, note="已存在，跳过")
                print(f"    {label:12s} 结构档已存在，跳过")
            else:
                blob = _post_or_none(fetcher, structures_ep, body)
                if blob is None:  # summary 有命中但结构档没有，属上游不一致，须留档
                    snap.skip("summary_hit_but_no_structures", label=label, query=body, rows=rows)
                    print(f"    {label:12s} ⚠ summary 有 {rows} 行但取不到结构档")
                    continue
                snap.write_bytes(tgz_name, blob, url=structures_ep,
                                 note=f"mmCIF 打包，对应 {rows} 条 instance")
                print(f"    {label:12s} structures  {len(blob):,} bytes")
            hit_labels += 1

    if not hit_labels:
        print("  ⚠ 所有 query 均无命中 —— 若非预期，先核对 binds_to_antigen "
              "用的是抗原全名而不是基因符号")


def run(reg: Registry, route: Route, snap: Snapshot, *, limit: int | None = None,
        dry_run: bool = False) -> None:
    if route.get("endpoint"):
        _all_summary(reg, route, snap, dry_run)
    elif route.get("queries"):
        _target_structures(reg, route, snap, limit, dry_run)
    else:
        raise DownloadError(
            f"route {route.route_id} 既没有 endpoint（全量 summary）"
            f"也没有 queries（按靶点检索），无法判断要做什么"
        )
