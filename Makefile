.PHONY: setup db-up db-down init reset smoke kpi
PY := ./.venv/bin/python

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
