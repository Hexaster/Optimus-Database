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

    def get(self, key, default=None):
        return self.spec.get(key, default)

    def require(self, key):
        if key not in self.spec:
            raise DownloadError(f"route {self.route_id} 缺少必填项 `{key}`")
        return self.spec[key]


@dataclass(frozen=True)
class Registry:
    path: Path
    raw: dict

    @property
    def source_name(self) -> str:
        return self.raw.get("source_name") or self.path.stem

    @property
    def download_config(self) -> dict:
        cfg = self.raw.get("下载配置")
        if not cfg:
            raise DownloadError(
                f"{self.path.name} 没有「下载配置」块 —— 该源尚未做成可执行的。\n"
                f"registry 的散文说明不足以驱动下载：查询串、筛选条件、翻页方式、\n"
                f"落盘文件名都必须显式写进「下载配置」。"
            )
        return cfg

    @property
    def downloader(self) -> str:
        return self.download_config["downloader"]

    @property
    def source_dir(self) -> str:
        return self.download_config.get("source_dir", self.path.stem)

    @property
    def http(self) -> dict:
        return self.download_config.get("http") or {}

    def route_ids(self) -> list[str]:
        return [r["route_id"] for r in self.download_config.get("routes", [])]

    def route(self, route_id: str | None = None) -> Route:
        routes = self.download_config.get("routes") or []
        if not routes:
            raise DownloadError(f"{self.path.name} 的「下载配置」里没有 routes")
        if route_id is None:
            if len(routes) > 1:
                raise DownloadError(
                    f"{self.path.name} 有多条 route，必须用 --route 指定其一："
                    + ", ".join(self.route_ids())
                )
            spec = routes[0]
        else:
            matched = [r for r in routes if r["route_id"] == route_id]
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
    if not candidate.is_file():
        stem = candidate.stem or name_or_path
        candidate = REGISTRY_DIR / f"{stem}.yaml"
    if not candidate.is_file():
        raise DownloadError(f"找不到 registry：{name_or_path}（查过 {candidate}）")
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


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


class Snapshot:
    """data/raw/<source_dir>/<snapshot>/ 这一层目录，外加一份 _manifest.json。

    目录约定沿用 cart_db.storage 的 raw_dir()，但这里不 import storage ——
    storage 会连带 import psycopg，而下载本身不需要数据库。
    """

    MANIFEST = "_manifest.json"

    def __init__(self, source_dir: str, snapshot: str | None = None):
        self.source_dir = source_dir
        self.snapshot = snapshot or date.today().strftime("%Y%m%d")
        self.dir = SETTINGS.data_root / "raw" / source_dir / self.snapshot
        self.dir.mkdir(parents=True, exist_ok=True)
        self.items: list[Downloaded] = []
        self.skipped: list[dict] = []

    def path(self, name: str) -> Path:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def done(self, name: str) -> bool:
        """已下过且非空 —— 用于断点续传，重跑不会重下几千篇全文。"""
        p = self.dir / name
        return p.is_file() and p.stat().st_size > 0

    def write_bytes(self, name: str, data: bytes, *, url=None, note=None) -> Path:
        p = self.path(name)
        p.write_bytes(data)
        self._record(p, url, note)
        return p

    def write_json(self, name: str, obj, *, url=None, note=None) -> Path:
        p = self.path(name)
        with p.open("w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        self._record(p, url, note)
        return p

    def adopt(self, name: str, *, url=None, note=None) -> None:
        """把一个已经在磁盘上的文件计入清单（断点续传时用）。"""
        self._record(self.dir / name, url, note)

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

    def skip(self, reason: str, **info) -> None:
        self.skipped.append({"reason": reason, **info})

    def finish(self, *, source_name: str, route_id: str, extra: dict | None = None) -> Path:
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
        with p.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        return p


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
_RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


class Fetcher:
    """带 UA、限速、重试的 HTTP 客户端。参数全部来自 registry 的 http 块。"""

    def __init__(self, http_cfg: dict | None = None):
        cfg = http_cfg or {}
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

    def _throttle(self) -> None:
        if self.rps <= 0:
            return
        gap = 1.0 / self.rps
        wait = gap - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        reraise=True,
    )
    def _get(self, url: str, **kw) -> httpx.Response:
        self._throttle()
        r = self.client.get(url, **kw)
        if r.status_code >= 500 or r.status_code == 429:
            r.raise_for_status()  # 交给 tenacity 重试
        return r

    def get(self, url: str, **kw) -> httpx.Response:
        return self._get(url, **kw)

    def get_json(self, url: str, **kw):
        r = self._get(url, **kw)
        r.raise_for_status()
        return r.json()

    def get_bytes(self, url: str, **kw) -> bytes:
        r = self._get(url, **kw)
        r.raise_for_status()
        return r.content

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        reraise=True,
    )
    def _post(self, url: str, **kw) -> httpx.Response:
        self._throttle()
        r = self.client.post(url, **kw)
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
        with self.client.stream("GET", url, **kw) as r:
            r.raise_for_status()
            # 有 content-encoding 时 httpx 交出的是解压后的字节，
            # 与 content-length（压缩后长度）不可比，这种情况不核对。
            declared = (
                None if r.headers.get("content-encoding")
                else r.headers.get("content-length")
            )
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
                    total += len(chunk)
        if declared is not None and total != int(declared):
            dest.unlink(missing_ok=True)  # 不留半个档在磁盘上冒充成功
            raise httpx.TransportError(
                f"下载不完整：{url} 声明 {int(declared):,} bytes，实收 {total:,} bytes"
            )
        return total

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

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

    endpoint = (
        route.get("endpoint")
        or route.get("search_endpoint")
        or route.get("manifest_endpoint")
        or route.get("index_url")
    )
    for item in snap.items:
        register(
            source_name=reg.source_name,
            local_path=snap.dir / item.file,
            api_endpoint=item.url or endpoint,
            file_format=(snap.dir / item.file).suffix.lstrip("."),
            snapshot_version=snap.snapshot,
            notes=f"route={route.route_id}",
        )
    return len(snap.items)
