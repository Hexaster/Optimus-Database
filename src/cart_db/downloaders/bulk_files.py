"""通用静态档下载器 —— 「一条 route = 一组固定 URL」的源都走这个。

目前服务两个源：
  thera_sabdab  单一 CSV（TheraSAbDab_SeqStruc_OnlineDownload.csv）
  dotad         下载中心的 9 个档（xlsx / zip / json）

这两个源都没有检索接口，全库就是这几个静态档，因此不按靶点过滤——
业务侧 2026-08-24 明确「对于 dotad 这种小数据库还是全部下载」，
靶点筛选留到 loader 阶段按 Target 栏做。

expected_bytes 是选填的漂移哨兵：DOTAD 不定期发版且档名不带日期，
大小变了就说明上游换了内容。不当错误抛，只记进 manifest 供人工复核。
"""
from __future__ import annotations

from .base import DownloadError, Fetcher, Registry, Route, Snapshot


# Download a configured list of static files, retaining individual failures and size-change
# warnings.
def run(reg: Registry, route: Route, snap: Snapshot, *, limit: int | None = None,
        dry_run: bool = False) -> None:
    base_url = route.get("base_url", "")
    files = route.require("files")
    # Use empty text when route.get('output_dir') is missing or empty.
    out_dir = (route.get("output_dir") or "").strip("/")

    # Apply the requested item limit before processing the selected inputs.
    if limit:
        files = files[:limit]

    # Preview the planned operation and return before the subsequent execution stage.
    if dry_run:
        # Process each f from files independently.
        for f in files:
            print(f"    [dry-run] {base_url}{f['name']}")
        return

    ok = resumed = 0
    # Reuse one configured HTTP client for this route and close it even after failure.
    with Fetcher(reg.http) as fetcher:
        # Process each f from files independently.
        for f in files:
            name = f["name"]
            # Prefer f.get('url'); if empty or absent, fall back to f'{base_url}{name}'.
            url = f.get("url") or f"{base_url}{name}"
            saved = f.get("save_as", name)
            # Use f'{out_dir}/{saved}' when out dir is truthy; otherwise use saved.
            local = f"{out_dir}/{saved}" if out_dir else saved

            # Reuse a nonempty downloaded file and retain it in the new manifest instead of
            # downloading again.
            if snap.done(local):
                snap.adopt(local, url=url, note=f.get("note"))
                resumed += 1
                print(f"    已存在，跳过  {local}")
                continue

            # Attempt this operation while preserving the explicit recovery/cleanup paths below.
            try:
                size = fetcher.stream_to(url, snap.path(local))
            except Exception as exc:  # 单档失败不该拖垮整批
                snap.skip("download_failed", name=name, url=url,
                          error=f"{type(exc).__name__}: {exc}")
                print(f"    ✗ {name}：{type(exc).__name__}")
                continue

            expected = f.get("expected_bytes")
            # When expected is not None and size != expected, report this outcome to the
            # command-line operator.
            if expected is not None and size != expected:
                print(f"    ⚠ {name} 实得 {size:,} bytes ≠ registry 记录的 {expected:,}，上游可能已改版")
                snap.skip("size_mismatch", name=name, expected=expected, actual=size)

            snap.adopt(local, url=url, note=f.get("note"))
            ok += 1
            print(f"    {size:>12,} bytes  {local}")

    print(f"  文件：新增 {ok}，已存在 {resumed}")
    # Stop with a diagnostic: 一个档都没拿到，检查 base_url 与 files.
    if not ok and not resumed:
        raise DownloadError("一个档都没拿到，检查 base_url 与 files")
