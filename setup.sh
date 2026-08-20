#!/usr/bin/env bash
# 一次性环境搭建：venv + 依赖 + 数据库 + 建表 + 冒烟测试
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 1/5 Python 虚拟环境"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt
echo "    依赖已锁定安装完成"

echo "==> 2/5 环境变量"
[ -f .env ] || { cp .env.example .env; echo "    已生成 .env（API key 先留空，本地建库不需要）"; }

echo "==> 3/5 PostgreSQL"
# Homebrew 的 postgresql@17 是 keg-only，不会进 PATH，这里自动探测
for kegs in /opt/homebrew/opt/postgresql@1[0-9]/bin /usr/local/opt/postgresql@1[0-9]/bin; do
  [ -d "$kegs" ] && export PATH="$kegs:$PATH"
done
if docker info >/dev/null 2>&1; then
  docker compose up -d
  echo -n "    等待数据库就绪"
  until docker compose exec -T db pg_isready -U cart -d cart >/dev/null 2>&1; do
    echo -n "."; sleep 1
  done; echo " 就绪"
elif command -v pg_isready >/dev/null 2>&1 && pg_isready -q; then
  echo "    使用本机已运行的 PostgreSQL"
else
  cat <<'MSG'
    未找到可用的 PostgreSQL。二选一：
      A. 装 Docker Desktop 后重跑本脚本（推荐，自带 pgvector）
      B. brew install postgresql@17 pgvector && brew services start postgresql@17
         然后 createuser -s cart && createdb -O cart cart
MSG
  exit 1
fi

echo "==> 4/5 建表"
./.venv/bin/python scripts/init_db.py

echo "==> 5/5 冒烟测试"
./.venv/bin/python scripts/smoke_test.py
