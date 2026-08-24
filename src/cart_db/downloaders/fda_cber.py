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


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-").lower()[:80]


def _clean(text: str) -> str:
    # 产品页大量使用 &nbsp;，转成普通空格再压缩
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _discover_products(html: str, base_url: str, path_prefix: str) -> list[dict]:
    doc = lxml.html.fromstring(html)
    out, seen = [], set()
    for a in doc.xpath("//a[@href]"):
        href = a.get("href").split("#")[0].split("?")[0]
        if not href.startswith(path_prefix) or href.rstrip("/") == path_prefix.rstrip("/"):
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if slug in seen:
            continue
        seen.add(slug)
        out.append({"slug": slug, "label": _clean(a.text_content()),
                    "url": urljoin(base_url, href)})
    return out


def _discover_documents(html: str, base_url: str, patterns: list[str]) -> list[dict]:
    doc = lxml.html.fromstring(html)
    out = []
    for a in doc.xpath("//a[@href]"):
        href = a.get("href")
        if "/media/" not in href or "/download" not in href:
            continue
        title = _clean(a.text_content())
        matched = next((p for p in patterns if p.lower() in title.lower()), None)
        if patterns and not matched:
            continue
        out.append({"title": title, "url": urljoin(base_url, href), "matched": matched})
    return out


def run(reg: Registry, route: Route, snap: Snapshot, *, limit: int | None = None,
        dry_run: bool = False) -> None:
    index_url = route.require("index_url")
    path_prefix = route.get("product_path_prefix",
                            "/vaccines-blood-biologics/cellular-gene-therapy-products/")
    wanted = [s.lower() for s in (route.get("products") or [])]
    patterns = route.get("document_title_contains") or []

    output = route.get("output") or {}
    products_index = output.get("products_index", PRODUCTS_INDEX_DEFAULT)
    documents_index = output.get("documents_index", DOCUMENTS_INDEX_DEFAULT)
    pdf_dir = output.get("pdf_dir", PDF_DIR_DEFAULT)

    with Fetcher(reg.http) as fetcher:
        # --- 1. 清单页 ---
        resp = fetcher.get(index_url)
        if resp.status_code == 404:
            raise DownloadError(
                "清单页返回 404。fda.gov 对非浏览器 User-Agent 就是这么回的，"
                "检查 registry 的 http.user_agent。"
            )
        resp.raise_for_status()
        products = _discover_products(resp.text, index_url, path_prefix)
        print(f"  清单页发现 {len(products)} 个产品")

        selected = [p for p in products if not wanted or p["slug"].lower() in wanted]
        missing = sorted(set(wanted) - {p["slug"].lower() for p in selected})
        if missing:
            # 记录而不是抛错：产品不在清单上本身就是要留证的结论。
            print(f"  ⚠ registry 点名但清单页没有的产品：{', '.join(missing)}")
            snap.skip("product_not_in_index", slugs=missing, index_url=index_url)

        snap.write_json(products_index,
                        {"index_url": index_url, "discovered": len(products),
                         "selected": [p["slug"] for p in selected], "products": products},
                        url=index_url, note="CGT 已批准产品清单页解析结果")

        if limit:
            selected = selected[:limit]

        # --- 2. 产品页 → 文档链接 ---
        per_product = []
        for p in selected:
            r = fetcher.get(p["url"])
            if r.status_code != 200:
                snap.skip(f"product_page_http_{r.status_code}", slug=p["slug"], url=p["url"])
                continue
            docs = _discover_documents(r.text, p["url"], patterns)
            per_product.append({**p, "documents": docs})
            print(f"    {p['slug']:12s} 匹配 {len(docs)} 份文档")
            if not docs:
                snap.skip("no_matching_document", slug=p["slug"], patterns=patterns)

        snap.write_json(documents_index,
                        {"document_title_contains": patterns, "products": per_product},
                        note="产品页解析出的 media id ↔ 文档标题对应关系")

        if dry_run:
            for p in per_product:
                for d in p["documents"]:
                    print(f"    [dry-run] {p['slug']:12s} {d['url']}  {d['title']}")
            return

        # --- 3. PDF ---
        ok = resumed = 0
        for p in per_product:
            for d in p["documents"]:
                name = f"{pdf_dir}/{p['slug']}_{_slug(d['title'])}.pdf"
                if snap.done(name):
                    snap.adopt(name, url=d["url"], note="已存在，跳过")
                    resumed += 1
                    continue
                try:
                    size = fetcher.stream_to(d["url"], snap.path(name))
                except Exception as exc:
                    snap.skip("pdf_download_failed", slug=p["slug"], url=d["url"],
                              error=f"{type(exc).__name__}: {exc}")
                    continue
                snap.adopt(name, url=d["url"], note=f"{p['label']} / {d['title']}")
                ok += 1
                print(f"    {p['slug']:12s} {size:>10,} bytes  {name}")

        print(f"  PDF：新增 {ok}，已存在 {resumed}")
