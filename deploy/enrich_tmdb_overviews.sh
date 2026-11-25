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
  *) echo "用法：sh deploy/enrich_tmdb_overviews.sh [--dry-run|--apply]" >&2; exit 2 ;;
esac

echo "将通过 TMDB 补充已核验影片的空缺剧情简介。"
echo "只补空字段；已由 TMDB 提供且接近六个月缓存期限的简介会先刷新，无法刷新时清除过期缓存。"
echo "执行前自动创建并校验 SQLite 备份；不会重启任何容器。"
docker compose build moviehub
docker compose run --rm --no-deps -T moviehub python -m scripts.import_tmdb_overviews "$MODE"
