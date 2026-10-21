"""Downloader 公共设施。

downloader 的定义（业务侧 2026-08-21 确认）：
    给定一份 SourceRegistry/*.yaml，把该源需要的数据下载到 data/raw/。

所以 downloader 只做「取数落盘」这一件事：
不解析、不做字段映射、不写业务表。
字段怎么变成数据库列写在 docs/Mapping/*.yaml，入库由后续 loader 负责。

可执行内容的唯一来源是 registry 里的「下载配置」块。
registry 的散文部分（notes / 取样验证）是给人看的，代码不读。
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import yaml
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .. import config

SETTINGS = config.settings
REGISTRY_DIR = config.ROOT / "docs" / "SourceRegistry"

# 默认表明身份，便于上游按 UA 联系我们。
# fda.gov 对非浏览器 UA 返回 404，那种源必须在 registry 的 http.user_agent 里改写。
DEFAULT_UA = "cart-db-downloader/0.1 (Fosun CAR-T ABC; research use)"


class DownloadError(RuntimeError):
    """下载失败，且不该靠重试解决。"""


class MissingCredentials(DownloadError):
    """凭证缺失。消息里必须写清楚需要哪个环境变量、怎么拿到。"""


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Route:
    route_id: str
    spec: dict

    # Read an optional route setting, returning the caller's default when absent.
    def get(self, key, default=None):
        return self.spec.get(key, default)

    # Read a mandatory route setting or explain which registry entry is missing.
    def require(self, key):
        # Stop with a diagnostic: route {self.route_id} 缺少必填项 `{key}`.
        if key not in self.spec:
            raise DownloadError(f"route {self.route_id} 缺少必填项 `{key}`")
        return self.spec[key]


@dataclass(frozen=True)
class Registry:
    path: Path
    raw: dict

    # Use the declared source name, falling back to the registry filename.
    @property
    def source_name(self) -> str:
        # Prefer self.raw.get('source_name'); if empty or absent, fall back to self.path.stem.
        return self.raw.get("source_name") or self.path.stem

    # Read the executable download block; prose-only source descriptions cannot drive downloads.
    @property
    def download_config(self) -> dict:
        cfg = self.raw.get("下载配置")
        # Stop with a diagnostic: {self.path.name} 没有「下载配置」块 —— 该源尚未做成可执行的。 registry
        # 的散文说明不足以驱动下载：查询串、筛选条件、翻页方式、 落盘文件名都必须显式写进「下载配置」。.
        if not cfg:
            raise DownloadError(
                f"{self.path.name} 没有「下载配置」块 —— 该源尚未做成可执行的。\n"
                f"registry 的散文说明不足以驱动下载：查询串、筛选条件、翻页方式、\n"
                f"落盘文件名都必须显式写进「下载配置」。"
            )
        return cfg

    # Return the source module selected by the registry configuration.
    @property
    def downloader(self) -> str:
        return self.download_config["downloader"]

    # Choose the raw snapshot directory name from the registry.
    @property
    def source_dir(self) -> str:
        return self.download_config.get("source_dir", self.path.stem)

    # Return per-source HTTP settings, or defaults when none are declared.
    @property
    def http(self) -> dict:
        # Use an empty mapping when self.download_config.get('http') is missing or empty.
        return self.download_config.get("http") or {}

    # List configured route identifiers for command-line discovery.
    def route_ids(self) -> list[str]:
        # Build mapped values from self.download_config.get('routes', []).
        return [r["route_id"] for r in self.download_config.get("routes", [])]

    # Resolve an explicit route, accepting an omitted ID only when the choice is unambiguous.
    def route(self, route_id: str | None = None) -> Route:
        # Use an empty list when self.download_config.get('routes') is missing or empty.
        routes = self.download_config.get("routes") or []
        # Stop with a diagnostic: {self.path.name} 的「下载配置」里没有 routes.
        if not routes:
            raise DownloadError(f"{self.path.name} 的「下载配置」里没有 routes")
        # Without an explicit route, allow only a registry with exactly one choice.
        if route_id is None:
            # Stop rather than continue with invalid or incomplete input.
            if len(routes) > 1:
                raise DownloadError(
                    f"{self.path.name} 有多条 route，必须用 --route 指定其一："
                    + ", ".join(self.route_ids())
                )
            spec = routes[0]
        # Find the requested route by ID and fail clearly if the registry does not define it.
        else:
            # Collect items from routes only where r['route_id'] == route_id.
            matched = [r for r in routes if r["route_id"] == route_id]
            # Stop rather than continue with invalid or incomplete input.
            if not matched:
                raise DownloadError(
                    f"{self.path.name} 没有 route `{route_id}`；可选："
                    + ", ".join(self.route_ids())
                )
            spec = matched[0]
        return Route(route_id=spec["route_id"], spec=spec)


def load_registry(name_or_path: str) -> Registry:
    """接受 `europe_pmc`、`europe_pmc.yaml` 或完整路径。"""
    candidate = Path(name_or_path)
    # Treat a non-file argument as a registry name and look under the registry directory.
    if not candidate.is_file():
        # Prefer candidate.stem; if empty or absent, fall back to name_or_path.
        stem = candidate.stem or name_or_path
        candidate = REGISTRY_DIR / f"{stem}.yaml"
    # Stop with a diagnostic: 找不到 registry：{name_or_path}（查过 {candidate}）.
    if not candidate.is_file():
        raise DownloadError(f"找不到 registry：{name_or_path}（查过 {candidate}）")
    # Close the file reliably, including when reading or writing raises an error.
    with candidate.open(encoding="utf-8") as fh:
        return Registry(path=candidate, raw=yaml.safe_load(fh))


# --------------------------------------------------------------------------
# 落盘
# --------------------------------------------------------------------------
@dataclass
class Downloaded:
    file: str
    bytes: int
    sha256: str
    url: str | None
    downloaded_at: str
    note: str | None = None


# Hash downloaded content in bounded chunks for the snapshot manifest.
def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    # Close the file reliably, including when reading or writing raises an error.
    with path.open("rb") as fh:
        # Read bounded chunks until EOF to avoid loading the whole file into memory.
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


class Snapshot:
    """data/raw/<source_dir>/<snapshot>/ 这一层目录，外加一份 _manifest.json。

    目录约定沿用 cart_db.storage 的 raw_dir()，但这里不 import storage ——
    storage 会连带 import psycopg，而下载本身不需要数据库。
    """

    MANIFEST = "_manifest.json"

    # Initialize snapshot paths and the file/skip manifest for one source run.
    def __init__(self, source_dir: str, snapshot: str | None = None):
        self.source_dir = source_dir
        # Prefer snapshot; if empty or absent, fall back to date.today().strftime('%Y%m%d').
        self.snapshot = snapshot or date.today().strftime("%Y%m%d")
        self.dir = SETTINGS.data_root / "raw" / source_dir / self.snapshot
        self.dir.mkdir(parents=True, exist_ok=True)
        self.items: list[Downloaded] = []
        self.skipped: list[dict] = []

    # Create parent directories for a file inside the source snapshot.
    def path(self, name: str) -> Path:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def done(self, name: str) -> bool:
        """已下过且非空 —— 用于断点续传，重跑不会重下几千篇全文。"""
        p = self.dir / name
        # A resumable download must be an actual file with nonzero size.
        return p.is_file() and p.stat().st_size > 0

    # Save bytes and immediately record the file's checksum and provenance.
    def write_bytes(self, name: str, data: bytes, *, url=None, note=None) -> Path:
        p = self.path(name)
        p.write_bytes(data)
        self._record(p, url, note)
        return p

    # Save readable Unicode JSON and record its checksum and provenance.
    def write_json(self, name: str, obj, *, url=None, note=None) -> Path:
        p = self.path(name)
        # Close the file reliably, including when reading or writing raises an error.
        with p.open("w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        self._record(p, url, note)
        return p

    def adopt(self, name: str, *, url=None, note=None) -> None:
        """把一个已经在磁盘上的文件计入清单（断点续传时用）。"""
        self._record(self.dir / name, url, note)

    # Append file size, checksum, source URL, and observation time to the snapshot inventory.
    def _record(self, p: Path, url, note) -> None:
        self.items.append(
            Downloaded(
                file=p.relative_to(self.dir).as_posix(),
                bytes=p.stat().st_size,
                sha256=_sha256(p),
                url=url,
                downloaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                note=note,
            )
        )

    # Retain the reason and identifiers for a file that was not downloaded.
    def skip(self, reason: str, **info) -> None:
        self.skipped.append({"reason": reason, **info})

    # Write a complete manifest describing downloaded files, skipped items, and run metadata.
    def finish(self, *, source_name: str, route_id: str, extra: dict | None = None) -> Path:
        # Build mapped values from self.items.
        manifest = {
            "source_name": source_name,
            "route_id": route_id,
            "snapshot": self.snapshot,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "file_count": len(self.items),
            "total_bytes": sum(i.bytes for i in self.items),
            "skipped_count": len(self.skipped),
            "files": [asdict(i) for i in self.items],
            "skipped": self.skipped,
            **(extra or {}),
        }
        p = self.dir / self.MANIFEST
        # Close the file reliably, including when reading or writing raises an error.
        with p.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        return p


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
_RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


class Fetcher:
    """带 UA、限速、重试的 HTTP 客户端。参数全部来自 registry 的 http 块。"""

    # Configure HTTP identity, timeout, and request rate for this source.
    def __init__(self, http_cfg: dict | None = None):
        # Use an empty mapping when http_cfg is missing or empty.
        cfg = http_cfg or {}
        # Default an absent/empty cfg.get('rate_limit_rps') to zero for this counter or estimate.
        self.rps = float(cfg.get("rate_limit_rps") or 0)
        self._last = 0.0
        # httpx 默认走 HTTP/1.1（未装 h2 时不会协商 http2）。
        # EMA 那份 29 MB 的 JSON 用 HTTP/2 会中途断流，显式关掉并在此留证。
        self.client = httpx.Client(
            headers={"User-Agent": cfg.get("user_agent") or DEFAULT_UA},
            timeout=httpx.Timeout(
                float(cfg.get("timeout_s", 60)),
                read=float(cfg.get("read_timeout_s", 300)),
            ),
            follow_redirects=True,
            http2=False,
        )

    # Enforce the configured minimum interval between HTTP requests.
    def _throttle(self) -> None:
        # When self.rps is at most 0, finish without producing another result.
        if self.rps <= 0:
            return
        gap = 1.0 / self.rps
        wait = gap - (time.monotonic() - self._last)
        # Sleep only for the remaining rate-limit interval; already elapsed time needs no extra
        # delay.
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    # Issue a rate-limited GET, raising transient server/throttle errors for the retry decorator.
    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        reraise=True,
    )
    def _get(self, url: str, **kw) -> httpx.Response:
        self._throttle()
        r = self.client.get(url, **kw)
        # Raise transient server/throttling failures so the retry policy can retry the request.
        if r.status_code >= 500 or r.status_code == 429:
            r.raise_for_status()  # 交给 tenacity 重试
        return r

    # Issue a GET through the rate-limited retry wrapper; callers choose how to handle its status.
    def get(self, url: str, **kw) -> httpx.Response:
        return self._get(url, **kw)

    # Fetch and status-check a response before decoding its JSON.
    def get_json(self, url: str, **kw):
        r = self._get(url, **kw)
        r.raise_for_status()
        return r.json()

    # Fetch and status-check a response before returning its raw bytes.
    def get_bytes(self, url: str, **kw) -> bytes:
        r = self._get(url, **kw)
        r.raise_for_status()
        return r.content

    # Issue a rate-limited POST with the same transient-error retry policy as GET.
    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        reraise=True,
    )
    def _post(self, url: str, **kw) -> httpx.Response:
        self._throttle()
        r = self.client.post(url, **kw)
        # Raise transient server/throttling failures so the retry policy can retry the request.
        if r.status_code >= 500 or r.status_code == 429:
            r.raise_for_status()  # 交给 tenacity 重试
        return r

    def post_bytes(self, url: str, **kw) -> bytes:
        """SAbDab 的按条件检索只接受 POST（同一 path 的 GET 返回 405）。"""
        r = self._post(url, **kw)
        r.raise_for_status()
        return r.content

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        reraise=True,
    )
    def stream_to(self, url: str, dest: Path, **kw) -> int:
        """大文件流式落盘，避免把 29 MB 先读进内存。

        必须和 _get 一样带重试：ema.europa.eu 实测会偶发 TLS 握手失败
        （SSL: UNEXPECTED_EOF_WHILE_READING），一次就把整批 PDF 拖垮。
        重试会重写整个档案，不做断点续传——半个 PDF 比没有更糟。

        落盘后核对 Content-Length。2026-08-24 实测 DOTAD 的
        entry_detail_by_id.json 会静默截断（应 19,308,835，实收 14,065,955，
        JSON 在第 104,021 行解析失败）——不核对就会把半个档当成功交给下游。
        截断抛 TransportError，由上面的 @retry 重下。
        """
        self._throttle()
        dest.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        # Release this managed resource when the enclosed operation completes or fails.
        with self.client.stream("GET", url, **kw) as r:
            r.raise_for_status()
            # 有 content-encoding 时 httpx 交出的是解压后的字节，
            # 与 content-length（压缩后长度）不可比，这种情况不核对。
            declared = (
                None if r.headers.get("content-encoding")
                else r.headers.get("content-length")
            )
            # Close the file reliably, including when reading or writing raises an error.
            with dest.open("wb") as fh:
                # Write response chunks incrementally and count bytes for completeness checks.
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
                    total += len(chunk)
        # When declared is not None and total != int(declared), remove the obsolete or incomplete
        # file.
        if declared is not None and total != int(declared):
            dest.unlink(missing_ok=True)  # 不留半个档在磁盘上冒充成功
            raise httpx.TransportError(
                f"下载不完整：{url} 声明 {int(declared):,} bytes，实收 {total:,} bytes"
            )
        return total

    # Release the HTTP connection pool.
    def close(self) -> None:
        self.client.close()

    # Expose the fetcher inside a with block.
    def __enter__(self):
        return self

    # Close the HTTP client even when a download raises an exception.
    def __exit__(self, *exc):
        self.close()


# --------------------------------------------------------------------------
# 可选：把落盘文件登记进 core.source_registry
# --------------------------------------------------------------------------
def register_snapshot(reg: Registry, snap: Snapshot, route: Route) -> int:
    """写 core.source_registry。需要数据库可用（psycopg + 已建表）。

    延迟 import：没有数据库时下载照样能跑，只是不登记。
    """
    from ..storage import register  # noqa: PLC0415 —— 见 docstring

    # Choose the first configured source endpoint for registration; per-file URLs can override it.
    endpoint = (
        route.get("endpoint")
        or route.get("search_endpoint")
        or route.get("manifest_endpoint")
        or route.get("index_url")
    )
    # Process each item from snap.items independently.
    for item in snap.items:
        # Prefer item.url; if empty or absent, fall back to endpoint.
        register(
            source_name=reg.source_name,
            local_path=snap.dir / item.file,
            api_endpoint=item.url or endpoint,
            file_format=(snap.dir / item.file).suffix.lstrip("."),
            snapshot_version=snap.snapshot,
            notes=f"route={route.route_id}",
        )
    return len(snap.items)
