"""数据源下载器。

一个 downloader = 给定一份 docs/SourceRegistry/*.yaml，
把该源需要的数据下载到 data/raw/<source_dir>/<snapshot>/。

它只负责取数落盘，不解析、不映射、不入库。
可执行内容全部来自 registry 的「下载配置」块；散文部分代码不读。

用法见 scripts/download.py。每个模块暴露同一个入口：
    run(reg: Registry, route: Route, snap: Snapshot, *, limit=None, dry_run=False) -> None
"""

KNOWN_DOWNLOADERS = (
    "europe_pmc",      # C 库文献语料
    "ema_epar",        # C 库监管文档
    "fda_cber",        # C 库监管文档
    "google_patents",  # A 库专利序列（需 GCP 凭证）
    "sabdab",          # A 库结构与序列
    "bulk_files",      # 通用：一组固定 URL。服务 thera_sabdab 与 dotad
)
