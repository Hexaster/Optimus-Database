"""FDA CBER downloader —— 已批准细胞与基因治疗产品的审评文档。

三段式：清单页 → 产品页 → PDF。

两个必须遵守的事实：
  1. fda.gov 对不带浏览器 User-Agent 的请求返回 404（不是 403），
     所以 registry 的 http.user_agent 必须写成浏览器 UA。
  2. 文档网址形如 /media/{数字}/download?attachment，完全不透明，
     必须从产品页解析「链接文字 → media id」的对应关系，不能猜、不能拼。

产品 slug 也不写死：从清单页动态发现，再按 registry 里的 products 匹配。
写死会掩盖上游变动 —— 实测 Abecma 与 Aucatzyl 就不在这张清单上。
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

import lxml.html

from .base import DownloadError, Fetcher, Registry, Route, Snapshot

PRODUCTS_INDEX_DEFAULT = "products_index.json"
DOCUMENTS_INDEX_DEFAULT = "documents_index.json"
PDF_DIR_DEFAULT = "documents"


# Build a bounded filesystem-friendly label from a document title.
def _slug(text: str) -> str:
    # Use empty text when text is missing or empty.
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-").lower()[:80]


# Normalize HTML nonbreaking spaces and layout whitespace in link labels.
def _clean(text: str) -> str:
    # 产品页大量使用 &nbsp;，转成普通空格再压缩
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


# Discover unique product URLs from the index page rather than guessing URL slugs.
def _discover_products(html: str, base_url: str, path_prefix: str) -> list[dict]:
    doc = lxml.html.fromstring(html)
    out, seen = [], set()
    # Inspect actual HTML links so download URLs come from the source page.
    for a in doc.xpath("//a[@href]"):
        href = a.get("href").split("#")[0].split("?")[0]
        # When not href.startswith(path_prefix) or href.rstrip('/') == path_prefix.rstrip('/'), skip
        # this item and continue checking the remaining inputs.
        if not href.startswith(path_prefix) or href.rstrip("/") == path_prefix.rstrip("/"):
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        # When slug is in seen, skip this item and continue checking the remaining inputs.
        if slug in seen:
            continue
        seen.add(slug)
        out.append({"slug": slug, "label": _clean(a.text_content()),
                    "url": urljoin(base_url, href)})
    return out


# Select document links by media URL and configured title patterns.
def _discover_documents(html: str, base_url: str, patterns: list[str]) -> list[dict]:
    doc = lxml.html.fromstring(html)
    out = []
    # Inspect actual HTML links so download URLs come from the source page.
    for a in doc.xpath("//a[@href]"):
        href = a.get("href")
        # When '/media/' not in href or '/download' not in href, skip this item and continue
        # checking the remaining inputs.
        if "/media/" not in href or "/download" not in href:
            continue
        title = _clean(a.text_content())
        # Collect items from patterns only where p.lower() in title.lower().
        matched = next((p for p in patterns if p.lower() in title.lower()), None)
        # When patterns and (not matched), skip this item and continue checking the remaining
        # inputs.
        if patterns and not matched:
            continue
        out.append({"title": title, "url": urljoin(base_url, href), "matched": matched})
    return out


# Follow the FDA index to product pages, save discovered links, and download matching PDFs.
def run(reg: Registry, route: Route, snap: Snapshot, *, limit: int | None = None,
        dry_run: bool = False) -> None:
    index_url = route.require("index_url")
    path_prefix = route.get("product_path_prefix",
                            "/vaccines-blood-biologics/cellular-gene-therapy-products/")
    # Build mapped values from route.get('products') or [].
    wanted = [s.lower() for s in (route.get("products") or [])]
    # Use an empty list when route.get('document_title_contains') is missing or empty.
    patterns = route.get("document_title_contains") or []

    # Use an empty mapping when route.get('output') is missing or empty.
    output = route.get("output") or {}
    products_index = output.get("products_index", PRODUCTS_INDEX_DEFAULT)
    documents_index = output.get("documents_index", DOCUMENTS_INDEX_DEFAULT)
    pdf_dir = output.get("pdf_dir", PDF_DIR_DEFAULT)

    with Fetcher(reg.http) as fetcher:
        # --- 1. 清单页 ---
        resp = fetcher.get(index_url)
        # Stop with a diagnostic: 清单页返回 404。fda.gov 对非浏览器 User-Agent 就是这么回的，检查 registry 的
        # http.user_agent。.
        if resp.status_code == 404:
            raise DownloadError(
                "清单页返回 404。fda.gov 对非浏览器 User-Agent 就是这么回的，"
                "检查 registry 的 http.user_agent。"
            )
        resp.raise_for_status()
        products = _discover_products(resp.text, index_url, path_prefix)
        print(f"  清单页发现 {len(products)} 个产品")

        # Collect items from products only where not wanted or p['slug'].lower() in wanted.
        selected = [p for p in products if not wanted or p["slug"].lower() in wanted]
        # Collect distinct values from selected.
        missing = sorted(set(wanted) - {p["slug"].lower() for p in selected})
        if missing:
            # 记录而不是抛错：产品不在清单上本身就是要留证的结论。
            print(f"  ⚠ registry 点名但清单页没有的产品：{', '.join(missing)}")
            snap.skip("product_not_in_index", slugs=missing, index_url=index_url)

        # Build mapped values from selected.
        snap.write_json(products_index,
                        {"index_url": index_url, "discovered": len(products),
                         "selected": [p["slug"] for p in selected], "products": products},
                        url=index_url, note="CGT 已批准产品清单页解析结果")

        # Apply the requested item limit before processing the selected inputs.
        if limit:
            selected = selected[:limit]

        # --- 2. 产品页 → 文档链接 ---
        per_product = []
        # Process each p from selected independently.
        for p in selected:
            r = fetcher.get(p["url"])
            # When r.status_code differs from 200, record the skipped download and its cause in the
            # snapshot.
            if r.status_code != 200:
                snap.skip(f"product_page_http_{r.status_code}", slug=p["slug"], url=p["url"])
                continue
            docs = _discover_documents(r.text, p["url"], patterns)
            per_product.append({**p, "documents": docs})
            print(f"    {p['slug']:12s} 匹配 {len(docs)} 份文档")
            # When docs is empty or false, record the skipped download and its cause in the
            # snapshot.
            if not docs:
                snap.skip("no_matching_document", slug=p["slug"], patterns=patterns)

        snap.write_json(documents_index,
                        {"document_title_contains": patterns, "products": per_product},
                        note="产品页解析出的 media id ↔ 文档标题对应关系")

        # Preview the planned operation and return before the subsequent execution stage.
        if dry_run:
            # Process each p from per_product independently.
            for p in per_product:
                # Process each d from p['documents'] independently.
                for d in p["documents"]:
                    print(f"    [dry-run] {p['slug']:12s} {d['url']}  {d['title']}")
            return

        # --- 3. PDF ---
        ok = resumed = 0
        # Process each p from per_product independently.
        for p in per_product:
            # Process each d from p['documents'] independently.
            for d in p["documents"]:
                name = f"{pdf_dir}/{p['slug']}_{_slug(d['title'])}.pdf"
                # Reuse a nonempty downloaded file and retain it in the new manifest instead of
                # downloading again.
                if snap.done(name):
                    snap.adopt(name, url=d["url"], note="已存在，跳过")
                    resumed += 1
                    continue
                # Attempt this operation while preserving the explicit recovery/cleanup paths below.
                try:
                    size = fetcher.stream_to(d["url"], snap.path(name))
                # On Exception, record the skipped download and its cause in the snapshot.
                except Exception as exc:
                    snap.skip("pdf_download_failed", slug=p["slug"], url=d["url"],
                              error=f"{type(exc).__name__}: {exc}")
                    continue
                snap.adopt(name, url=d["url"], note=f"{p['label']} / {d['title']}")
                ok += 1
                print(f"    {p['slug']:12s} {size:>10,} bytes  {name}")

        print(f"  PDF：新增 {ok}，已存在 {resumed}")
