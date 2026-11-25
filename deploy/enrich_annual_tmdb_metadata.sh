#!/bin/sh
set -eu

ROOT="/volume1/docker/moviehub"
cd "$ROOT"
if [ "$(pwd -P)" != "$ROOT" ]; then
  echo "拒绝执行：必须从生产目录 $ROOT 运行" >&2
  exit 1
fi

MODE="${1:---dry-run}"
case "$MODE" in
  --dry-run|--apply) ;;
  *) echo "用法：sh deploy/enrich_annual_tmdb_metadata.sh [--dry-run|--apply]" >&2; exit 2 ;;
esac

echo "将使用年度榜单已有 TMDB ID 补全空缺元数据。"
echo "只补原名、年份、演员、类型和地区；保留已有值、豆瓣评分、榜单排名和简介。"
echo "默认只读预检；--apply 才会写入，并在写入前创建及校验 SQLite 备份。"
echo "此操作不重启任何运行中的容器。"
docker compose build moviehub
docker compose run --rm --no-deps -T moviehub python -m scripts.enrich_annual_tmdb_metadata "$MODE"
