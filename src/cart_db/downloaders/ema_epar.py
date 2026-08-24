"""EMA EPAR downloader —— 文档清单 JSON + assessment report PDF。

两段式：先用 20,121 条的文档清单 JSON 定位 PDF，再把 PDF 拉下来。
清单本身一个工艺字段都填不了，工艺内容全在 assessment report 正文里。

坑：清单 JSON 有 29 MB，走 HTTP/2 会中途断流
（curl 报 "HTTP/2 stream 1 was not closed cleanly: INTERNAL_ERROR"，档案截断成 12.9 MB）。
base.Fetcher 固定 http2=False，这里再用流式落盘，两处一起避开。
"""
from __future__ import annotations

import json
import re

from .base import DownloadError, Fetcher, Registry, Route, Snapshot

MANIFEST_FILE_DEFAULT = "epar_documents_all.json"
SUBSET_FILE_DEFAULT = "epar_documents_subset.json"
PDF_DIR_DEFAULT = "documents"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-").lower()


def run(reg: Registry, route: Route, snap: Snapshot, *, limit: int | None = None,
        dry_run: bool = False) -> None:
    endpoint = route.require("manifest_endpoint")
    flt = route.get("filter") or {}
    medicines = {m.lower() for m in (flt.get("medicine_name_in") or [])}
    doc_types = {t.lower() for t in (flt.get("type_in") or [])}
    expected = route.get("expected_records")

    output = route.get("output") or {}
    manifest_file = output.get("manifest", MANIFEST_FILE_DEFAULT)
    subset_file = output.get("subset", SUBSET_FILE_DEFAULT)
    pdf_dir = output.get("pdf_dir", PDF_DIR_DEFAULT)

    with Fetcher(reg.http) as fetcher:
        # --- 1. 文档清单 ---
        manifest_path = snap.path(manifest_file)
        if snap.done(manifest_file):
            print(f"  清单已存在，跳过下载：{manifest_file}")
            snap.adopt(manifest_file, url=endpoint, note="已存在，跳过")
        else:
            size = fetcher.stream_to(endpoint, manifest_path)
            print(f"  清单下载完成：{size:,} bytes")
            snap.adopt(manifest_file, url=endpoint, note="EPAR 全量文档清单")

        with manifest_path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        records = payload.get("data") or []
        meta = payload.get("meta") or {}
        print(f"  清单共 {meta.get('total_records', len(records)):,} 条，"
              f"timestamp={meta.get('timestamp')}")

        # --- 2. 筛选 ---
        subset = [
            r for r in records
            if (not medicines or (r.get("medicine_name") or "").lower() in medicines)
            and (not doc_types or (r.get("type") or "").lower() in doc_types)
        ]
        found = sorted({r.get("medicine_name") for r in subset})
        print(f"  筛出 {len(subset)} 条：{', '.join(found)}")
        if expected is not None and len(subset) != expected:
            # 不抛错——上游是 rolling 的，条数变化本身就是要记录的事实。
            print(f"  ⚠ 与 registry 的 expected_records={expected} 不符，已计入 manifest")
            snap.skip("expected_records_mismatch", expected=expected, actual=len(subset))
        missing = sorted(medicines - {(m or "").lower() for m in found})
        if missing:
            print(f"  ⚠ 清单里没有这些产品：{', '.join(missing)}")
            snap.skip("medicine_not_in_manifest", medicines=missing)

        if limit:
            subset = subset[:limit]
        if dry_run:
            for r in subset:
                print(f"    [dry-run] {r.get('medicine_name'):10s} {r.get('type')} "
                      f"→ {r.get('document_url')}")
            return

        snap.write_json(subset_file, {"filter": flt, "count": len(subset), "data": subset},
                        note="按产品与文档类型筛出的子集")

        # --- 3. PDF ---
        ok = resumed = 0
        for r in subset:
            url = r.get("document_url")
            if not url:
                snap.skip("no_document_url", id=r.get("id"), medicine=r.get("medicine_name"))
                continue
            name = f"{pdf_dir}/{_slug(r.get('medicine_name'))}_{_slug(r.get('type'))}.pdf"
            if snap.done(name):
                snap.adopt(name, url=url, note="已存在，跳过")
                resumed += 1
                continue
            try:
                size = fetcher.stream_to(url, snap.path(name))
            except Exception as exc:  # 单篇失败不该拖垮整批
                snap.skip("pdf_download_failed", url=url, medicine=r.get("medicine_name"),
                          error=f"{type(exc).__name__}: {exc}")
                continue
            snap.adopt(name, url=url,
                       note=f"{r.get('medicine_name')} / {r.get('ema_product_number')} / "
                            f"first_published={r.get('first_published_date')}")
            ok += 1
            print(f"    {r.get('medicine_name'):10s} {size:>10,} bytes  {name}")

        print(f"  PDF：新增 {ok}，已存在 {resumed}")
        if not ok and not resumed:
            raise DownloadError("一份 PDF 都没拿到，检查 filter 与 document_url")
