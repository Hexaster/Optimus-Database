# Legacy targets: current setup/import instructions are in README.md.
# Override PY for your interpreter; the extract target references a retired script.
.PHONY: setup db-up db-down init reset smoke kpi extract \
        download-epar download-sbra download-litc download-patents \
        download-therasabdab download-sabdab download-dotad download-binder
PY ?= /home/zzz010122/anaconda3/envs/fosun/bin/python

setup:   ## 一次性搭好环境（venv + 依赖 + 数据库 + 建表 + 冒烟）
	./setup.sh
db-up:   ## 启动本地数据库
	docker compose up -d
db-down: ## 停止数据库（数据保留在 volume）
	docker compose down
init:    ## 执行建表脚本（幂等，可反复跑）
	$(PY) scripts/init_db.py
reset:   ## 整库删除后重建 —— Schema 改动后用这个
	$(PY) scripts/init_db.py --reset
smoke:   ## 端到端冒烟测试
	$(PY) scripts/smoke_test.py
kpi:     ## 打印当前数量指标，抄进跟踪表「5.数量指标KPI」
	$(PY) -c "from cart_db.db import kpi; [print(f'{k:24s} {v}') for k,v in kpi().items()]"

# ---- 文本抽取 ------------------------------------------------------------
extract:  ## 从一份 PDF/XML/MD 抽取数据：make extract FILE=data/raw/europe_pmc/x.xml
	$(PY) scripts/extract.py $(FILE) $(ARGS)

# ---- 原始数据下载 --------------------------------------------------------
# 通用形态：$(PY) scripts/download.py <registry> --route <id> [--limit N] [--dry-run]
# 加 --dry-run 可先看要下什么再决定。
download-epar:    ## C库主源：7 个 CAR-T 产品的 EMA EPAR assessment report
	$(PY) scripts/download.py ema_epar --route assessment_reports
download-sbra:    ## C库补充：FDA CBER 的 SBRA（注意 (b)(4) 涂黑，定量参数拿不到）
	$(PY) scripts/download.py fda_cber_cgt --route sbra
download-litc:    ## C库定量字段唯一来源：Europe PMC 工艺语料全文 XML
	$(PY) scripts/download.py europe_pmc --route process_corpus
download-patents: ## A库专利来源：Google Patents BigQuery（需 GCP 凭证，见 registry）
	$(PY) scripts/download.py google_patents --route cart_binder_patents

# A 库。小库全量下载，大库（SAbDab 结构档）只取 GCC/CDH17。
download-therasabdab: ## A库：Thera-SAbDab 全量 CSV（INN + VH/VL + Target）
	$(PY) scripts/download.py thera_sabdab --route seqstruc
download-dotad:       ## A库：DOTAD 2.0 下载中心九档（约 130 MB，含 103 MB 亲和力基准）
	$(PY) scripts/download.py dotad --route all_files
download-sabdab:      ## A库：SAbDab 全量 summary + GCC/CDH17 结构档
	$(PY) scripts/download.py sabdab --route all_summary
	$(PY) scripts/download.py sabdab --route target_structures
download-binder:      ## A库一把梭：上面三个源全跑（Google Patents 另需凭证，不含在内）
	$(MAKE) download-therasabdab download-dotad download-sabdab
